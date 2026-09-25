import base64
import json
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from lp5_to_loupix import Converter


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/WZkAAAAASUVORK5CYII=')


class ConverterTest(unittest.TestCase):
    def test_embedded_icon_and_unmapped_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.lp5'
            page_id = 'page'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('ApplicationInfo.json', '{}')
                archive.writestr('ProfileInfo.json', json.dumps({'layout': {'layoutModes': [{
                    'touchPages': [{'name': page_id, 'controls': [
                        {'pressAction': '$@Generic___@MouseClick'},
                        {'pressAction': '$Unknown___Action'},
                        {'pressAction': '$@Generic___@None'},
                    ]}],
                    'encoderPages': [{'name': 'dials', 'controls': [
                        {'rotateAction': '$Unknown___Adjustment'},
                    ]}],
                    'workspaces': [{'name': 'workspace', 'touchPageNames': [page_id],
                                    'encoderPageNames': ['dials']}],
                }]}}))
                archive.writestr('ActionIcons/%24%40Generic___%40MouseClick.ict', json.dumps({
                    'items': [{'itemType': 'Image', 'isVisible': True,
                               'image': base64.b64encode(PNG).decode(),
                               'area': {'x': 9, 'y': 0, 'width': 82, 'height': 82}},
                              {'itemType': 'Text', 'isVisible': True, 'text': 'LABEL',
                               'fontSize': 4,
                               'area': {'x': 0, 'y': 82, 'width': 100, 'height': 18}}],
                }))
            converter = Converter(source, None)
            manifest, payload, report = converter.convert()
            buttons = payload['Profile']['Workspaces'][0]['TouchButtonPages'][0]['TouchButtons']
            icon = buttons[0]['States'][0]['Layers'][0]
            placeholder = buttons[1]['States'][0]['Layers'][0]
            self.assertEqual(icon['kind'], 'image')
            self.assertIn(icon['AssetRelativePath'], manifest['Assets'])
            self.assertEqual(converter.asset_blobs[icon['AssetRelativePath']], PNG)
            self.assertIsNone(buttons[1]['Command'])
            self.assertIn('Not imported', placeholder['Text'])
            self.assertLessEqual(placeholder['TextSize'], 10)
            self.assertEqual(buttons[1]['States'][0]['BackColor'], '#54202B')
            self.assertTrue(buttons[1]['States'][0]['BackgroundEnabled'])
            caption = buttons[0]['States'][0]['Layers'][1]
            self.assertEqual(caption['TextSize'], 12)
            self.assertLessEqual(caption['PositionY'], 27)
            self.assertLessEqual(icon['Scale'], .65)
            self.assertEqual(buttons[2]['States'][0]['Layers'], [])
            rotary = payload['Profile']['Workspaces'][0]['LeftRotaryButtonPages'][0]['RotaryButtons'][0]
            self.assertEqual(rotary['DisplayText'], '')
            self.assertEqual(report['unsupported'][0]['reason'], 'unmapped-action')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'SVG conversion requires ffmpeg')
    def test_small_svg_is_rasterized_at_display_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.lp5'
            svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="12" fill="white"/></svg>'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('ApplicationInfo.json', '{}')
                archive.writestr('ProfileInfo.json', json.dumps({'layout': {'layoutModes': [{
                    'touchPages': [{'name': 'page', 'controls': [{'pressAction': '$DefaultWin___MediaPlayPause'}]}],
                    'workspaces': [{'name': 'workspace', 'touchPageNames': ['page']}],
                }]}}))
                archive.writestr('ActionIcons/%24DefaultWin___MediaPlayPause.ict', json.dumps({
                    'items': [{'itemType': 'Image', 'isVisible': True,
                               'image': base64.b64encode(svg).decode(),
                               'area': {'x': 0, 'y': 0, 'width': 100, 'height': 100}}],
                }))
            converter = Converter(source, None)
            _, payload, _ = converter.convert()
            icon = payload['Profile']['Workspaces'][0]['TouchButtonPages'][0]['TouchButtons'][0]['States'][0]['Layers'][0]
            png = converter.asset_blobs[icon['AssetRelativePath']]
            self.assertEqual(struct.unpack('>II', png[16:24]), (240, 240))

    def test_rotary_icon_is_placed_on_side_strip(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.lp5'
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('ApplicationInfo.json', '{}')
                archive.writestr('ProfileInfo.json', json.dumps({'layout': {'layoutModes': [{
                    'encoderPages': [{'name': 'dials', 'controls': [
                        {'rotateAction': '$DefaultWin___Volume'},
                        {'rotateAction': '$Unknown___Adjustment'}, {},
                        {'rotateAction': '$@Generic___@MouseWheel'},
                    ]}],
                    'workspaces': [{'name': 'workspace', 'encoderPageNames': ['dials']}],
                }]}}))
                archive.writestr('ActionIcons/%24DefaultWin___Volume.ict', json.dumps({
                    'items': [{'itemType': 'Image', 'isVisible': True,
                               'image': base64.b64encode(PNG).decode(),
                               'area': {'x': 0, 'y': 0, 'width': 100, 'height': 100}}],
                }))
                archive.writestr('ActionIcons/%24Unknown___Adjustment.ict', json.dumps({
                    'items': [{'itemType': 'Image', 'isVisible': True,
                               'image': base64.b64encode(PNG).decode(),
                               'area': {'x': 0, 'y': 0, 'width': 100, 'height': 80}},
                              {'itemType': 'Text', 'isVisible': True, 'text': 'Original label',
                               'fontSize': 9,
                               'area': {'x': 0, 'y': 80, 'width': 100, 'height': 20}}],
                }))
            converter = Converter(source, None)
            manifest, payload, _ = converter.convert()
            workspace = payload['Profile']['Workspaces'][0]
            left = workspace['LeftRotaryButtonPages'][0]
            right = workspace['RightRotaryButtonPages'][0]
            self.assertEqual(left['StripMode'], 1)
            self.assertEqual(right['StripMode'], 0)
            self.assertEqual(left['StripCanvas']['Index'], 12)
            layers = left['StripCanvas']['States'][0]['Layers']
            image = next(layer for layer in layers if layer['kind'] == 'image')
            self.assertIn(image['AssetRelativePath'], manifest['Assets'])
            self.assertEqual(image['Scale'], 1.0)
            self.assertEqual([layer['Text'] for layer in layers if layer['kind'] == 'text'], ['Original label'])


if __name__ == '__main__':
    unittest.main()
