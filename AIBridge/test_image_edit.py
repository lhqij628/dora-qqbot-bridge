import asyncio
import base64
import json
import logging
import hashlib
import struct
import tempfile
import unittest
import zlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

import bridge


def blue_png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = (b'\x00' + b'\x00\x00\xff' * 256) * 256
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 256, 256, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


class Store:
    def __init__(self, config):
        self.config = config

    async def get(self):
        return deepcopy(self.config)


class ImageEditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.response = {'data': [{'b64_json': base64.b64encode(blue_png()).decode()}]}
        self.status = 200
        self.download_auth = None

        async def reference(request):
            self.download_auth = request.headers.get('Authorization')
            return web.Response(body=blue_png(), content_type='image/png')

        async def upstream(request):
            if request.content_type == 'multipart/form-data':
                fields = []
                reader = await request.multipart()
                async for part in reader:
                    fields.append((part.name, part.filename, part.headers.get('Content-Type'), bytes(await part.read())))
                self.calls.append((request.path, request.headers.get('Authorization'), fields))
            else:
                self.calls.append((request.path, request.headers.get('Authorization'), await request.json()))
            return web.json_response(self.response, status=self.status)

        app = web.Application()
        app.router.add_get('/reference', reference)
        app.router.add_post('/v1/images/edits', upstream)
        app.router.add_post('/v1/images/generations', upstream)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.base = 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])
        self.config = deepcopy(bridge.DEFAULT_CONFIG)
        for section in ('image', 'image_edit'):
            self.config[section].update(enabled=True, base_url=self.base + '/v1', api_key='test-key')
        self.config['memory']['enabled'] = False
        self.config['chat']['enabled'] = False
        self.bot = bridge.LLBotAIBridge(Store(self.config))
        self.bot.logger = logging.getLogger('image-edit-test')
        self.bot.reply = AsyncMock()
        self.bot.session = ClientSession()
        self.ref = 'base64://' + base64.b64encode(blue_png()).decode()

    async def asyncTearDown(self):
        if self.bot.background_tasks:
            await asyncio.gather(*self.bot.background_tasks)
        await self.bot.session.close()
        await self.runner.cleanup()

    async def test_openai_multipart_and_reference_download_has_no_key(self):
        await self.bot.reply_image({}, 'make it green', self.config, image_refs=[self.base + '/reference'])
        path, auth, fields = self.calls[0]
        self.assertEqual(path, '/v1/images/edits')
        self.assertEqual(auth, 'Bearer test-key')
        self.assertIsNone(self.download_auth)
        self.assertEqual(dict((x[0], x[3]) for x in fields)['model'], b'gpt-image-fast')
        upload = next(x for x in fields if x[0] == 'image')
        self.assertEqual(upload[2:], ('image/png', blue_png()))
        self.assertEqual(self.bot.reply.call_args.args[1][0]['type'], 'image')

    async def test_multiple_images_and_url_response(self):
        self.response = {'data': [{'url': 'https://example.com/result.png'}]}
        await self.bot.reply_image({}, 'edit both', self.config, image_refs=[self.ref, self.ref])
        uploads = [x for x in self.calls[0][2] if x[0] == 'image[]']
        self.assertEqual(len(uploads), 2)
        self.assertEqual(self.bot.reply.call_args.args[1][0]['data']['file'], self.response['data'][0]['url'])

    async def test_invalid_missing_and_oversize_reference_never_submit(self):
        for refs in ([], ['base64://aW52YWxpZA=='], ['base64://%%%']):
            await self.bot.reply_image({}, 'edit', self.config, image_refs=refs)
        with self.assertRaises(ValueError):
            bridge.image_upload_type(b'\x89PNG\r\n\x1a\n' + b'x' * bridge.MAX_EDIT_IMAGE_BYTES)
        self.assertEqual(self.calls, [])

    async def test_error_and_empty_result_do_not_send_image_or_retry(self):
        for status, response in ((429, {'error': 'rate limited'}), (200, {'data': []}), (200, [])):
            self.status, self.response = status, response
            await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
            self.assertIsInstance(self.bot.reply.call_args.args[1], str)
        self.assertEqual(len(self.calls), 3)

    async def test_text_to_image_still_uses_json_generation_endpoint(self):
        await self.bot.reply_image({}, 'a tree', self.config)
        self.assertEqual(self.calls[0][0], '/v1/images/generations')
        self.assertEqual(self.calls[0][2]['prompt'], 'a tree')

    async def test_api_connection_and_response_timeouts_are_distinct_without_retry(self):
        for error, expected in (
            (bridge.ConnectionTimeoutError(), '连接超时'),
            (asyncio.TimeoutError(), '等待生图 API 响应超时'),
        ):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.bot.session, 'post') as post:
                    post.return_value.__aenter__.side_effect = error
                    await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
                    post.assert_called_once()
                message = self.bot.reply.call_args.args[1]
                self.assertIn(expected, message)
                self.assertNotIn('5分钟', message)
                self.assertNotIn('排队', message)
        self.assertEqual(self.calls, [])

    async def test_reference_timeout_never_submits_generation(self):
        self.bot.load_edit_image = AsyncMock(side_effect=bridge.ConnectionTimeoutError())
        with patch.object(self.bot.session, 'post') as post:
            await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
            post.assert_not_called()
        self.assertIn('参考图片下载超时', self.bot.reply.call_args.args[1])

    async def test_delivery_timeout_does_not_claim_api_failed_or_regenerate(self):
        self.bot.reply.side_effect = [asyncio.TimeoutError(), None]
        await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.bot.reply.await_count, 2)
        self.assertIn('生图 API 已返回图片', self.bot.reply.call_args.args[1])

    async def test_windows_network_error_and_disconnect_do_not_retry_generation(self):
        windows_error = OSError(0, 'semaphore timeout', None, 121)
        # Linux ignores the Windows-specific OSError constructor argument.
        windows_error.winerror = 121
        for error in (windows_error, bridge.ClientConnectionError('connection reset')):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.bot.session, 'post') as post:
                    post.return_value.__aenter__.side_effect = error
                    await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
                    post.assert_called_once()
                message = self.bot.reply.call_args.args[1]
                self.assertIn('与生图服务通信时发生网络错误', message)
                self.assertIn('任务状态未知', message)
                self.assertNotIn('尚未提交', message)
                if error is windows_error:
                    self.assertIn('Windows 121', message)
        self.assertEqual(self.calls, [])

    async def test_response_body_network_error_does_not_claim_generation_completed(self):
        with patch.object(self.bot.session, 'post') as post:
            response = post.return_value.__aenter__.return_value
            response.status = 200
            response.text = AsyncMock(side_effect=bridge.ClientConnectionError('connection reset'))
            await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
            post.assert_called_once()
        self.assertIn('任务状态未知', self.bot.reply.call_args.args[1])

    async def test_reference_io_failure_never_submits_and_delivery_failure_never_regenerates(self):
        with patch.object(self.bot, 'load_edit_image', AsyncMock(side_effect=OSError('unavailable'))):
            await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
        self.assertEqual(self.calls, [])
        self.assertIn('尚未提交生图请求', self.bot.reply.call_args.args[1])
        self.bot.reply.side_effect = [bridge.ClientConnectionError('disconnected'), None]
        await self.bot.reply_image({}, 'edit', self.config, image_refs=[self.ref])
        self.assertEqual(len(self.calls), 1)
        self.assertIn('生图 API 已返回图片', self.bot.reply.call_args.args[1])

    async def test_fixed_selfie_uploads_saved_identity_not_quoted_or_cached_image(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge, 'SELFIE_REFERENCE_DIR', Path(folder)):
            name = hashlib.sha256(blue_png()).hexdigest() + '.png'
            (Path(folder) / name).write_bytes(blue_png())
            self.config['selfie'].update(enabled=True, reference_image=name, identity_prompt='银发蓝眼，动漫画风')
            self.config['image']['enabled'] = False
            self.bot.remember_seen_images('group:123:sender:11', ['base64://aW52YWxpZA=='])
            self.bot.call_action = AsyncMock()
            await self.run_event(self.quoted_event('朵啦发张自拍，在公园，比例9:16'))
            self.bot.call_action.assert_not_awaited()
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.calls[0][0], '/v1/images/edits')
            fields = dict((x[0], x[3]) for x in self.calls[0][2])
            self.assertEqual(fields['image'], blue_png())
            prompt = fields['prompt'].decode()
            self.assertIn('银发蓝眼', prompt)
            self.assertIn('在公园', prompt)
            self.assertNotIn('真实手机前置摄像头风格', prompt)
            self.assertNotEqual(fields['size'], b'auto')

    async def test_persona_url_sent_as_json_without_downloading_or_loading_local_reference(self):
        reference_url = 'https://cdn.example.com/dora.png?version=2&size=large'
        self.config['selfie'].update(enabled=True, reference_url=reference_url, reference_image='missing.png')
        self.bot.load_edit_image = AsyncMock(side_effect=AssertionError('must not download reference'))
        with patch.object(self.bot.session, 'get', side_effect=AssertionError('must not fetch URL')):
            await self.run_event(self.event('朵啦发张自拍'))
        self.bot.load_edit_image.assert_not_awaited()
        self.assertEqual(len(self.calls), 1)
        path, authorization, payload = self.calls[0]
        self.assertEqual(path, '/v1/images/edits')
        self.assertEqual(authorization, 'Bearer test-key')
        self.assertEqual(payload['images'], [{'image_url': reference_url}])
        self.assertEqual(payload['model'], 'gpt-image-fast')
        self.assertNotIn('image', payload)
        self.assertEqual(self.bot.reply.call_args.args[1][0]['type'], 'image')

    async def test_url_request_failure_never_falls_back_or_retries_upload(self):
        self.config['selfie'].update(enabled=True, reference_url='https://cdn.example.com/dora.png')
        self.status, self.response = 400, {'error': {'message': 'URL input unsupported'}}
        self.bot.load_edit_image = AsyncMock()
        await self.run_event(self.event('朵啦发张自拍'))
        self.assertEqual(len(self.calls), 1)
        self.bot.load_edit_image.assert_not_awaited()
        self.assertIn('URL input unsupported', self.bot.reply.call_args.args[1])

    async def test_invalid_persona_url_never_falls_back_to_local_or_submits(self):
        self.config['selfie'].update(enabled=True, reference_url='file:///C:/picture.png')
        self.bot.load_edit_image = AsyncMock()
        await self.run_event(self.event('朵啦发张自拍'))
        self.assertEqual(self.calls, [])
        self.bot.load_edit_image.assert_not_awaited()
        self.assertIn('人物参考图地址无效', self.bot.reply.call_args.args[1])

    def test_reference_url_validation_and_secret_preserving_config_round_trip(self):
        url = 'https://cdn.example.com/dora.png?x=1&y=2'
        updated = bridge.clean_update(self.config, {'selfie': {'reference_url': '  '+url+'  '}})
        self.assertEqual(updated['selfie']['reference_url'], url)
        public = bridge.public_config(updated)
        self.assertEqual(bridge.clean_update(updated, public)['image_edit']['api_key'], 'test-key')
        self.assertEqual(bridge.clean_update(updated, {'selfie': {'reference_url': ''}})['selfie']['reference_url'], '')
        for bad in ('file:///C:/picture.png', 'https://localhost/pic', 'http://127.0.0.1/a',
                    'http://10.0.0.1/a', 'https://[::1]/a', 'https://user:pass@example.com/a',
                    'https://example.com:bad/a', 'https://example.com/a\nb', 'https://example.com/a#fragment'):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                bridge.clean_update(updated, {'selfie': {'reference_url': bad}})

    async def test_reference_url_can_be_saved_reloaded_and_invalid_update_is_rejected(self):
        with patch.object(bridge, 'load_config', return_value=deepcopy(self.config)), patch.object(bridge, 'save_config') as save:
            store = bridge.ConfigStore()
            async with TestClient(TestServer(bridge.make_app(store, self.bot))) as client:
                response = await client.put('/api/config', json={'selfie': {'reference_url': 'https://cdn.example.com/dora.png'}})
                self.assertEqual(response.status, 200)
                response = await client.get('/api/config')
                self.assertEqual((await response.json())['data']['selfie']['reference_url'], 'https://cdn.example.com/dora.png')
                response = await client.put('/api/config', json={'selfie': {'reference_url': 'file:///bad'}})
                self.assertEqual(response.status, 400)
                self.assertEqual((await store.get())['selfie']['reference_url'], 'https://cdn.example.com/dora.png')
                save.assert_called_once()

    async def test_at_bot_and_private_selfie_requests_use_fixed_route(self):
        self.config['selfie']['enabled'] = True
        self.bot.reply_selfie = AsyncMock()
        event = self.event('发张自拍')
        event['message'].insert(0, {'type': 'at', 'data': {'qq': '99'}})
        await self.run_event(event)
        event = self.event('发个自拍')
        event['message_type'] = 'private'
        event.pop('group_id')
        await self.run_event(event)
        self.assertEqual(self.bot.reply_selfie.await_count, 2)
        self.assertEqual(self.calls, [])

    async def test_selfie_followup_keeps_saved_identity(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge, 'SELFIE_REFERENCE_DIR', Path(folder)):
            name = hashlib.sha256(blue_png()).hexdigest() + '.png'
            (Path(folder) / name).write_bytes(blue_png())
            self.config['selfie'].update(enabled=True, reference_image=name)
            self.config['image']['enabled'] = False
            await self.run_event(self.event('朵啦发张自拍'))
            await self.run_event(self.event('再来一张，在公园'))
            self.assertEqual(len(self.calls), 2)
            self.assertTrue(all(call[0] == '/v1/images/edits' for call in self.calls))
            fields = dict((x[0], x[3]) for x in self.calls[1][2])
            self.assertEqual(fields['image'], blue_png())
            self.assertIn('在公园', fields['prompt'].decode())

    async def test_activity_is_text_first_then_photo_uses_actual_answer_and_fixed_reference(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge, 'SELFIE_REFERENCE_DIR', Path(folder)):
            name = hashlib.sha256(blue_png()).hexdigest() + '.png'
            (Path(folder) / name).write_bytes(blue_png())
            self.config['selfie'].update(enabled=True, reference_image=name)
            self.config['chat']['enabled'] = True
            self.bot.chat = AsyncMock(return_value='在食堂吃番茄鸡蛋面呢')
            self.bot.remember_image_request('group:123', '一只小猫', None)
            self.bot.remember_seen_images('group:123', [self.ref])
            await self.run_event(self.event('看看朵啦在干嘛'))
            self.bot.chat.assert_awaited_once()
            self.assertEqual(self.calls, [])
            self.assertEqual(self.bot.reply.call_args.args[1], '在食堂吃番茄鸡蛋面呢')
            # Other senders' replies must not replace this sender's scene.
            self.bot.chat.return_value = '在图书馆读书'
            await self.run_event(self.event('朵啦在干嘛', user=11))
            await self.run_event(self.event('发个图片看看'))
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(self.calls[0][0], '/v1/images/edits')
            fields = dict((x[0], x[3]) for x in self.calls[0][2])
            self.assertEqual(fields['image'], blue_png())
            self.assertIn('在食堂吃番茄鸡蛋面呢', fields['prompt'].decode())
            self.assertNotIn('在图书馆读书', fields['prompt'].decode())

    async def test_persona_context_expires_and_does_not_cross_group_or_user(self):
        self.config['selfie']['enabled'] = True
        self.bot.reply_selfie = AsyncMock()
        context_key = 'group:123:sender:10'
        self.bot.persona_context[context_key] = {'question': '在干嘛', 'answer': '在吃饭', 'time': bridge.time.time()}
        await self.run_event(self.event('发个图片看看', user=11))
        other_group = self.event('发个图片看看')
        other_group['group_id'] = 789
        await self.run_event(other_group)
        self.bot.persona_context[context_key]['time'] = 0
        await self.run_event(self.event('发个图片看看'))
        self.bot.reply_selfie.assert_not_awaited()

    async def test_unrelated_chat_and_api_errors_do_not_keep_old_activity(self):
        self.config['selfie']['enabled'] = True
        self.config['chat']['enabled'] = True
        self.bot.chat = AsyncMock(return_value='在吃饭')
        self.bot.reply_selfie = AsyncMock()
        await self.run_event(self.event('朵啦在干嘛'))
        self.bot.chat.return_value = '二加二等于四'
        await self.run_event(self.event('朵啦，二加二等于几'))
        self.assertFalse(self.bot.recent_persona_context('group:123:sender:10'))
        self.bot.chat.return_value = '聊天 API 调用失败：服务繁忙'
        await self.run_event(self.event('朵啦在干嘛'))
        self.assertFalse(self.bot.recent_persona_context('group:123:sender:10'))
        self.bot.reply_selfie.assert_not_awaited()

    def test_persona_photo_intent_does_not_capture_other_images_or_configuration_questions(self):
        for text in ('朵啦在干嘛', '看看朵啦在干嘛', '朵啦帮我生成一张猫图片',
                     '生成一张小猫图片', '不要发照片', '朵啦自拍怎么设置', '/图生图 改成朵啦的照片'):
            self.assertFalse(bridge.persona_photo_request(text, True, True), text)
        for text in ('朵啦发张自拍', '看看朵啦的形象', '看看朵啦长什么样', '生成一张朵啦在吃饭的照片', '发个图片看看'):
            self.assertTrue(bridge.persona_photo_request(text, True, True), text)

    async def test_explicit_draw_of_persona_uses_reference_but_draw_of_cat_does_not(self):
        self.config['selfie']['enabled'] = True
        self.bot.reply_selfie = AsyncMock()
        await self.run_event(self.event('/画图 朵啦在吃饭的照片'))
        self.bot.reply_selfie.assert_awaited_once()
        self.assertEqual(self.calls, [])
        self.bot.reply_selfie.reset_mock()
        await self.run_event(self.event('朵啦帮我生成一张小猫图片'))
        self.bot.reply_selfie.assert_not_awaited()
        self.assertEqual(self.calls[0][0], '/v1/images/generations')

    async def test_fixed_selfie_missing_reference_or_disabled_edits_never_falls_back(self):
        self.config['selfie']['enabled'] = True
        for reference, edit_enabled in (('', True), ('../config.json', True), ('a' * 64 + '.png', True), ('', False)):
            self.config['selfie']['reference_image'] = reference
            self.config['image_edit']['enabled'] = edit_enabled
            await self.run_event(self.event('朵啦发张自拍'))
            self.assertIsInstance(self.bot.reply.call_args.args[1], str)
        self.assertEqual(self.calls, [])

    async def test_selfie_disabled_retains_original_text_generation(self):
        await self.run_event(self.event('朵啦发张自拍'))
        self.assertEqual(self.calls[0][0], '/v1/images/generations')

    def test_selfie_detection_rejects_negation_and_explicit_other_commands(self):
        for text in ('别发自拍', '不要自拍', '/语音 说朵啦发自拍', '/图生图 把照片改成朵啦自拍'):
            self.assertEqual(bridge.selfie_prompt_from_text(text, allow_implicit=True), '')
        self.assertEqual(bridge.selfie_prompt_from_text('发张自拍'), '')
        self.assertTrue(bridge.selfie_prompt_from_text('发张自拍', allow_implicit=True))

    async def test_reference_upload_preview_and_invalid_data_are_isolated_from_config(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bridge, 'SELFIE_REFERENCE_DIR', Path(folder)):
            async with TestClient(TestServer(bridge.make_app(Store(self.config), self.bot))) as client:
                response = await client.post('/api/selfie/reference', data=blue_png())
                self.assertEqual(response.status, 200)
                name = (await response.json())['reference_image']
                self.assertEqual(self.config['selfie']['reference_image'], '')
                response = await client.get('/api/selfie/reference/' + name)
                self.assertEqual(await response.read(), blue_png())
                response = await client.get('/api/selfie/reference/config.json')
                self.assertEqual(response.status, 404)
                response = await client.post('/api/selfie/reference', data=b'not an image')
                self.assertEqual(response.status, 400)
                with patch.object(bridge, 'MAX_EDIT_IMAGE_BYTES', 32):
                    response = await client.post('/api/selfie/reference', data=b'x' * 33)
                    self.assertEqual(response.status, 413)
                self.assertEqual(len(list(Path(folder).iterdir())), 1)

    async def test_safety_rewrite_runs_before_image_edit(self):
        risky = '裸体色情照片'
        self.assertTrue(bridge.image_prompt_risk_reasons(risky))
        self.bot.rewrite_image_prompt_for_safety = AsyncMock(return_value='safe portrait')
        await self.bot.reply_image({}, risky, self.config, image_refs=[self.ref])
        fields = dict((x[0], x[3]) for x in self.calls[0][2])
        self.assertEqual(fields['prompt'], b'safe portrait')

    def event(self, text, user=10, image=False):
        msg = [{'type': 'text', 'data': {'text': text}}]
        if image:
            msg.append({'type': 'image', 'data': {'url': self.ref}})
        return {'post_type': 'message', 'message_type': 'group', 'group_id': 123,
                'self_id': 99, 'user_id': user, 'message': msg, 'sender': {'nickname': 'tester'}}

    async def run_event(self, event):
        await self.bot.handle_event(event)
        if self.bot.background_tasks:
            await asyncio.gather(*self.bot.background_tasks)

    async def test_attached_edit_command_keeps_ratio(self):
        await self.run_event(self.event('/图生图 改成绿色 比例16:9', image=True))
        self.assertEqual(len(self.calls), 1)
        fields = dict((x[0], x[3]) for x in self.calls[0][2])
        self.assertNotEqual(fields['size'], b'auto')
        self.assertNotIn(b'16:9', fields['prompt'])

    async def test_previous_image_isolated_per_sender(self):
        await self.run_event(self.event('', image=True))
        await self.run_event(self.event('/图生图 改成绿色', user=11))
        self.assertEqual(self.calls, [])
        await self.run_event(self.event('改成绿色'))
        self.assertEqual(len(self.calls), 1)

    async def test_vision_question_stays_in_chat(self):
        self.config['chat']['enabled'] = True
        self.bot.chat = AsyncMock(return_value='blue square')
        await self.run_event(self.event('这图是什么', image=True))
        self.assertEqual(self.calls, [])
        self.bot.chat.assert_awaited_once()

    async def test_cached_image_expires(self):
        self.bot.remember_seen_images('group:123:sender:10', [self.ref])
        self.bot.last_seen_images['group:123:sender:10']['time'] = 0
        await self.run_event(self.event('/图生图 改成绿色'))
        self.assertEqual(self.calls, [])

    async def test_cached_image_does_not_capture_plain_generation(self):
        await self.run_event(self.event('', image=True))
        await self.run_event(self.event('生成一张小猫图片'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], '/v1/images/generations')

    async def test_attached_draw_command_and_natural_edit(self):
        for text in ('/画图 改成绿色', '把背景换成绿色'):
            await self.run_event(self.event(text, image=True))
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(call[0] == '/v1/images/edits' for call in self.calls))

    async def test_empty_edit_prompt_never_submits(self):
        await self.run_event(self.event('/图生图', image=True))
        self.assertEqual(self.calls, [])

    async def test_edit_disabled_leaves_existing_generation_command(self):
        self.config['image_edit']['enabled'] = False
        await self.run_event(self.event('/画图 一只小猫', image=True))
        self.assertEqual(self.calls[0][0], '/v1/images/generations')

    def quoted_event(self, text):
        event = self.event(text, user=11)
        event['message'].insert(0, {'type': 'reply', 'data': {'id': '456'}})
        return event

    def quoted_message(self):
        return {'message_type': 'group', 'group_id': 123, 'user_id': 10,
                'message_id': 456, 'message': [{'type': 'image', 'data': {'url': self.ref}}]}

    async def test_quote_another_sender_uses_get_msg_then_uploads(self):
        actions = []
        bot = self.bot
        quoted = self.quoted_message()

        class Socket:
            async def send_str(self, payload):
                action = json.loads(payload)
                actions.append(action)
                bot.resolve_action_response({'status': 'ok', 'retcode': 0, 'echo': action['echo'], 'data': quoted})

        self.bot.ws = Socket()
        await self.run_event(self.quoted_event('/图生图 改成绿色'))
        self.assertEqual(actions[0]['action'], 'get_msg')
        self.assertEqual(actions[0]['params'], {'message_id': '456'})
        self.assertEqual(self.calls[0][0], '/v1/images/edits')
        upload = next(x for x in self.calls[0][2] if x[0] == 'image')
        self.assertEqual(upload[3], blue_png())

    async def test_quoted_edit_supports_natural_language_and_draw_command(self):
        self.bot.call_action = AsyncMock(return_value=self.quoted_message())
        for text in ('改成动漫风格', '把背景换成海边', '/画图 加一棵树', '生成一张同风格图片'):
            await self.run_event(self.quoted_event(text))
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(x[0] == '/v1/images/edits' for x in self.calls))

    async def test_quoted_subject_edit_overrides_previous_text_generation(self):
        self.bot.call_action = AsyncMock(return_value=self.quoted_message())
        self.bot.remember_image_request('group:123', '机甲少女', None)
        event = self.quoted_event('机甲改成红色')
        event['message'].insert(1, {'type': 'at', 'data': {'qq': '99'}})
        await self.run_event(event)
        self.bot.call_action.assert_awaited_once_with('get_msg', {'message_id': '456'}, wait=True, timeout=10)
        self.assertEqual(self.calls[0][0], '/v1/images/edits')
        fields = dict((x[0], x[3]) for x in self.calls[0][2])
        self.assertEqual(fields['prompt'].decode(), '机甲改成红色')
        self.assertEqual(fields['image'], blue_png())

    async def test_subject_edits_use_current_or_same_sender_reference(self):
        for text in ('机甲改成红色', '衣服换成蓝色', '头发改为黑色'):
            await self.run_event(self.event(text, image=True))
        await self.run_event(self.event('背景调整为夜晚'))
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(x[0] == '/v1/images/edits' for x in self.calls))

    def test_subject_edit_without_image_context_is_not_image_edit(self):
        self.assertEqual(bridge.image_edit_prompt_from_text('机甲改成红色'), ('', False))

    async def test_explicit_quote_overrides_sender_cache(self):
        self.bot.remember_seen_images('group:123:sender:11', ['base64://aW52YWxpZA=='])
        self.bot.call_action = AsyncMock(return_value=self.quoted_message())
        await self.run_event(self.quoted_event('改成绿色'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.bot.recent_seen_images('group:123:sender:11'), [self.ref])

    async def test_unavailable_empty_and_other_group_quotes_never_fall_back(self):
        self.bot.remember_seen_images('group:123:sender:11', [self.ref])
        quoted = self.quoted_message()
        for response in (None, {**quoted, 'message': []}, {**quoted, 'group_id': 789},
                         {**quoted, 'status': 'deleted'}, {**quoted, 'message_type': 'private'}):
            self.bot.call_action = AsyncMock(return_value=response)
            await self.run_event(self.quoted_event('/图生图 改成绿色'))
            self.assertIsInstance(self.bot.reply.call_args.args[1], str)
        self.assertEqual(self.calls, [])

    async def test_quote_lookup_timeout_does_not_fall_back(self):
        self.bot.remember_seen_images('group:123:sender:11', [self.ref])
        self.bot.call_action = AsyncMock(side_effect=asyncio.TimeoutError)
        await self.run_event(self.quoted_event('/图生图 改成绿色'))
        self.assertEqual(self.calls, [])
        self.assertIn('读取引用图片失败', self.bot.reply.call_args.args[1])
        self.assertEqual(self.bot.call_action.call_args.kwargs['timeout'], 10)

    async def test_cq_string_quote_and_raw_image_message(self):
        event = self.quoted_event('/图生图 改成绿色')
        event['message'] = '[CQ:reply,id=456][CQ:at,qq=99] /图生图 改成绿色'
        quoted = self.quoted_message()
        quoted['message'] = ''
        quoted['raw_message'] = '[CQ:image,file=' + self.ref + ']'
        self.bot.call_action = AsyncMock(return_value=quoted)
        await self.run_event(event)
        self.assertEqual(len(self.calls), 1)
        fields = dict((x[0], x[3]) for x in self.calls[0][2])
        self.assertEqual(fields['prompt'].decode(), '改成绿色')
        self.assertEqual(bridge.image_refs_from_message('[CQ:image,url=https://example.com/a?a=1&amp;b=2&#44;x]'),
                         ['https://example.com/a?a=1&b=2,x'])

    async def test_ordinary_reply_does_not_fetch_or_generate(self):
        self.bot.call_action = AsyncMock()
        await self.run_event(self.quoted_event('今天好热'))
        self.bot.call_action.assert_not_awaited()
        self.assertEqual(self.calls, [])

    async def test_private_quote_checks_conversation(self):
        event = self.quoted_event('/图生图 改成绿色')
        event['message_type'] = 'private'
        event.pop('group_id')
        for user_id, target_id in ((11, None), (99, 11)):
            quoted = {**self.quoted_message(), 'message_type': 'private', 'user_id': user_id, 'target_id': target_id}
            quoted.pop('group_id')
            self.bot.call_action = AsyncMock(return_value=quoted)
            await self.run_event(event)
        self.assertEqual(len(self.calls), 2)
        self.bot.call_action = AsyncMock(return_value={**quoted, 'target_id': 333})
        await self.run_event(event)
        self.assertEqual(len(self.calls), 2)

    def test_secret_round_trip(self):
        public = bridge.public_config(self.config)
        self.assertEqual(public['image_edit']['api_key'], '')
        self.assertEqual(bridge.clean_update(self.config, public)['image_edit']['api_key'], 'test-key')


if __name__ == '__main__':
    unittest.main()
