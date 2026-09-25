#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import uuid
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


def guid() -> str:
    return str(uuid.uuid4())


def command_encode(value: str) -> str:
    # Mirrors LoupixDeck CommandParameterEncoding.Encode.
    return (value.replace('%', '%25')
                 .replace('(', '%28')
                 .replace(')', '%29')
                 .replace(',', '%2C')
                 .replace('&', '%26'))


def json_load_bytes(data: bytes) -> Any:
    return json.loads(data.decode('utf-8-sig'))


KEY_MAP = {
    'ControlOrCommand': 'Ctrl',
    'Control': 'Ctrl',
    'AltOrOption': 'Alt',
    'Windows': 'Win',
    'ArrowUp': 'Up',
    'ArrowDown': 'Down',
    'ArrowLeft': 'Left',
    'ArrowRight': 'Right',
    'Back': 'Backspace',
    'Delete': 'Del',
    'PageUp': 'PageUp',
    'PageDown': 'PageDown',
    'Add': 'NumPlus',
    'Subtract': 'NumMinus',
    # WPF/Windows OEM names -> physical US-position names understood by LoupixDeck.
    'Oem1': 'Semicolon',
    'Oem2': 'Slash',
    'Oem4': 'LeftBracket',
    'Oem5': 'Backslash',
    'Oem6': 'RightBracket',
    'Oem7': 'Quote',
}


def normalize_key_combo(raw: str | None) -> str | None:
    if not raw:
        return None
    combo = raw.split('___', 1)[0].strip()
    if not combo:
        return None
    out: list[str] = []
    for token in combo.split('+'):
        token = token.strip()
        if not token:
            # Loupedeck sometimes stores a literal + as an empty token. Preserve it.
            out.append('+')
            continue
        if token.startswith('Key') and len(token) > 3:
            token = token[3:]
        token = KEY_MAP.get(token, token)
        out.append(token)
    return '+'.join(out)


def blank_wallpaper() -> dict[str, Any]:
    return {
        'AssetPath': None,
        'VideoPath': None,
        'VideoName': None,
        'VideoFps': 30,
        'Scaling': 100,
        'PositionX': 0,
        'PositionY': 0,
        'ScalingOption': 2,
        'Mirror': False,
        'Opacity': 0.0,
    }


def wrap() -> dict[str, Any]:
    return {'PreEnabled': False, 'PreCommands': '', 'PostEnabled': False, 'PostCommands': ''}


def text_layer(text: str, name: str = 'Imported label') -> dict[str, Any]:
    text = (text or '').strip()
    if len(text) > 28:
        text = text[:27] + '…'
    return {
        'kind': 'text',
        'BoxWidth': 0,
        'BoxHeight': 0,
        'Text': text,
        'TextSize': 13 if len(text) > 12 else 16,
        'TextColor': 'White',
        'Bold': False,
        'Italic': False,
        'Outlined': False,
        'OutlineColor': 'Black',
        'Centered': True,
        'Id': guid(),
        'Name': name,
        'OwnerKey': None,
        'Visible': True,
        'PositionX': 0,
        'PositionY': 0,
        'Scale': 1.0,
        'ScaleY': 0.0,
        'SourceRect': {'Left': 0.0, 'Top': 0.0, 'Right': 0.0, 'Bottom': 0.0},
        'Rotation': 0.0,
    }


def image_layer(asset_path: str, name: str = 'Imported icon') -> dict[str, Any]:
    return {
        'kind': 'image',
        'AssetRelativePath': asset_path,
        'AnimatedAssetPath': None,
        'Id': guid(),
        'Name': name,
        'OwnerKey': None,
        'Visible': True,
        'PositionX': 0,
        'PositionY': 0,
        'Scale': 1.0,
        'ScaleY': 0.0,
        'Rotation': 0.0,
    }


def make_touch_button(index: int, command: str | None, layers: list[dict[str, Any]]) -> dict[str, Any]:
    sid = guid()
    state = {
        'Id': sid,
        'Name': 'Default',
        'Command': command,
        'LedColor': 'Black',
        'VibrationEnabled': False,
        'VibrationPattern': 51,
        'Transition': {'Kind': 0, 'TargetStateId': None},
        'BackColor': 'Black',
        'BackgroundEnabled': False,
        'Layers': layers,
    }
    return {
        'Index': index,
        'States': [state],
        'DefaultStateId': sid,
        'Mode': 0,
        'ResetOnPageChange': False,
        'ResetOnRestart': True,
        'Command': command,
        'IgnoreRefresh': False,
        'EnableWhenOff': False,
    }



def make_simple_button(button_id: int, command: str | None, led_color: str | None = None) -> dict[str, Any]:
    sid = guid()
    color = led_color or ('Blue' if command else 'Black')
    state = {
        'Id': sid,
        'Name': 'Default',
        'Command': command,
        'LedColor': color,
        'VibrationEnabled': False,
        'VibrationPattern': 51,
        'Transition': {'Kind': 0, 'TargetStateId': None},
        'BackColor': 'Black',
        'BackgroundEnabled': False,
        'Layers': [],
    }
    return {
        'Id': button_id,
        'States': [state],
        'DefaultStateId': sid,
        'Mode': 0,
        'ResetOnPageChange': False,
        'ResetOnRestart': True,
        'Command': command,
        'IgnoreRefresh': False,
        'EnableWhenOff': False,
    }



def make_rotary_button(index: int, label: str, left: str | None, right: str | None, press: str | None) -> dict[str, Any]:
    return {
        'Index': index,
        'DisplayText': textwrap.shorten(label, width=18, placeholder='…') if label else '',
        'RotaryLeftCommand': left or '',
        'RotaryRightCommand': right or '',
        'Command': press,
        'IgnoreRefresh': False,
        'EnableWhenOff': False,
    }


def make_rotary_page(name: str, page_num: int, side: int, buttons: list[dict[str, Any]],
                     strip_canvas: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'RotaryButtons': buttons,
        'Side': side,
        'StripMode': 1 if strip_canvas else 0,
        'StripCanvas': strip_canvas,
        'StripSegmentCommands': None,
        'StripPluginId': None,
        'SimpleButtonWrap': wrap(),
        'KnobLeftWrap': wrap(),
        'KnobRightWrap': wrap(),
        'KnobPressWrap': wrap(),
        'Id': guid(),
        'Name': name or '',
        'Page': page_num,
    }


def make_touch_page(name: str, page_num: int, buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'TouchButtons': buttons,
        'MainWallpaper': blank_wallpaper(),
        'LeftWallpaper': blank_wallpaper(),
        'RightWallpaper': blank_wallpaper(),
        'TouchButtonWrap': wrap(),
        'Id': guid(),
        'Name': name or '',
        'Page': page_num,
    }


class Converter:
    def __init__(self, lp5_path: Path, template_path: Path | None):
        self.lp5_path = lp5_path
        self.template_path = template_path
        self.zip = zipfile.ZipFile(lp5_path, 'r')
        self.app = json_load_bytes(self.zip.read('ApplicationInfo.json'))
        self.profile = json_load_bytes(self.zip.read('ProfileInfo.json'))
        self.layout_mode = (self.profile.get('layout', {}).get('layoutModes') or [{}])[0]

        self.template_manifest = self._read_template_manifest(template_path)
        self.target_touch_count = int(self.template_manifest.get('SourceTouchButtonCount', 14))
        self.target_rotary_count = int(self.template_manifest.get('SourceRotaryButtonCount', 6))
        self.target_side_strips = bool(self.template_manifest.get('SourceHasSideStrips', True))

        self.touch_pages_by_id = {p.get('name'): p for p in self.layout_mode.get('touchPages') or [] if p.get('name')}
        self.encoder_pages_by_id = {p.get('name'): p for p in self.layout_mode.get('encoderPages') or [] if p.get('name')}
        self.workspaces = self.layout_mode.get('workspaces') or []
        self.workspace_by_old = {w.get('name'): w for w in self.workspaces if w.get('name')}

        self.workspace_guid_by_old: dict[str, str] = {w.get('name'): guid() for w in self.workspaces if w.get('name')}
        self.profile_actions = {a.get('name'): a for a in self.profile.get('profileActions') or [] if a.get('name')}
        self.macro_commands = {m.get('name'): m for m in self.profile.get('macroCommands') or [] if m.get('name')}
        self.macro_adjustments = {m.get('name'): m for m in self.profile.get('macroAdjustments') or [] if m.get('name')}

        self.action_images = self._index_action_images()
        self.action_icons = self._index_action_icons()
        self.asset_blobs: dict[str, bytes] = {}
        self.asset_paths: set[str] = set()
        self.referenced_commands: set[str] = set()

        self.stats = Counter()
        self.unsupported = Counter()
        self.unsupported_examples: dict[str, str] = {}
        self.notes: list[str] = []

    def _read_template_manifest(self, template_path: Path | None) -> dict[str, Any]:
        if template_path is None:
            return {
                'ConfigSchemaVersion': 13,
                'SourceDeviceSlug': 'razer-stream-controller',
                'SourceDeviceName': 'Razer Stream Controller',
                'SourceTouchButtonCount': 14,
                'SourceRotaryButtonCount': 6,
                'SourceHasSideStrips': True,
                'AppVersion': 'unknown',
            }
        with zipfile.ZipFile(template_path, 'r') as z:
            return json_load_bytes(z.read('manifest.json'))

    def _index_action_images(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in self.zip.namelist():
            if not name.startswith('ActionImages/') or not name.lower().endswith('.png'):
                continue
            base = Path(name).name[:-4]
            decoded = urllib.parse.unquote(base)
            result.setdefault(decoded, name)
        return result

    def _index_action_icons(self) -> dict[str, str]:
        return {
            urllib.parse.unquote(Path(name).stem): name
            for name in self.zip.namelist()
            if name.startswith('ActionIcons/') and name.lower().endswith('.ict')
        }

    def _find_image(self, action_ref: str | None) -> str | None:
        if not action_ref:
            return None
        if action_ref in self.action_images:
            return self.action_images[action_ref]
        # Prefer state0000 for old multi-state actions.
        state0 = action_ref + '___state0000'
        if state0 in self.action_images:
            return self.action_images[state0]
        for decoded, archive_name in self.action_images.items():
            if decoded.startswith(action_ref + '___'):
                return archive_name
        return None

    def _import_asset(self, archive_name: str) -> str:
        return self._store_asset(self.zip.read(archive_name), Path(archive_name).suffix.lower())

    def _store_asset(self, data: bytes, ext: str = '.png') -> str:
        sha = hashlib.sha256(data).hexdigest()
        rel = f'assets/{sha}{ext}'
        self.asset_blobs[rel] = data
        self.asset_paths.add(rel)
        return rel

    def _svg_to_png(self, data: bytes) -> bytes | None:
        if not shutil.which('ffmpeg'):
            return None
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'icon.svg'
            output = Path(directory) / 'icon.png'
            source.write_bytes(data)
            try:
                result = subprocess.run(
                    ['ffmpeg', '-v', 'error', '-width', '240', '-height', '240',
                     '-i', str(source), '-frames:v', '1', str(output)],
                    capture_output=True, timeout=15, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            return output.read_bytes() if result.returncode == 0 and output.exists() else None

    def _icon_layers(self, ref: str) -> list[dict[str, Any]]:
        archive_name = self.action_icons.get(ref)
        if not archive_name:
            return []
        icon = json_load_bytes(self.zip.read(archive_name))
        layers = []
        for item in icon.get('items') or []:
            if not item.get('isVisible'):
                continue
            if item.get('itemType') == 'Image' and item.get('image'):
                try:
                    data = base64.b64decode(item['image'], validate=True)
                except (ValueError, base64.binascii.Error):
                    self._unsupported(ref, 'unsupported-icon-image')
                    continue
                if data.lstrip().startswith(b'<svg'):
                    data = self._svg_to_png(data)
                if data and data.startswith(b'\x89PNG\r\n\x1a\n'):
                    layer = image_layer(self._store_asset(data))
                    area = item.get('area') or {}
                    layer['Scale'] = float(area.get('width', 100)) / 100
                    layer['PositionX'] = (float(area.get('x', 0)) + float(area.get('width', 100)) / 2 - 50) * .9
                    layer['PositionY'] = (float(area.get('y', 0)) + float(area.get('height', 100)) / 2 - 50) * .9
                    layers.append(layer)
                    self.stats['icons_copied'] += 1
                else:
                    self._unsupported(ref, 'unsupported-icon-image')
            elif item.get('itemType') == 'Text' and item.get('text'):
                layer = text_layer(item['text'])
                area = item.get('area') or {}
                layer['BoxWidth'] = round(float(area.get('width', 100)) * .9)
                layer['BoxHeight'] = round(float(area.get('height', 100)) * .9)
                layer['PositionX'] = (float(area.get('x', 0)) + float(area.get('width', 100)) / 2 - 50) * .9
                layer['PositionY'] = (float(area.get('y', 0)) + float(area.get('height', 100)) / 2 - 50) * .9
                layer['TextSize'] = max(8, int(item.get('fontSize') or 8))
                layers.append(layer)
        return layers

    def _mark_command_names(self, command: str | None) -> None:
        if not command:
            return
        for segment in command.split('&&'):
            segment = segment.strip()
            if not segment:
                continue
            name = segment.split('(', 1)[0].strip()
            if name:
                self.referenced_commands.add(name)

    def _unsupported(self, ref: str, why: str) -> None:
        key = why
        self.unsupported[key] += 1
        self.unsupported_examples.setdefault(key, ref)

    def _label_for_ref(self, ref: str | None) -> str:
        if not ref or ref in ('$@Generic___@None', '@None'):
            return ''
        if ref.startswith('$@Generic___@ProfileAction___'):
            a = self.profile_actions.get(ref)
            return (a or {}).get('displayName') or 'Profile action'
        if ref.startswith('$@Generic___@Macro___'):
            mid = ref.rsplit('___', 1)[-1]
            return (self.macro_commands.get(mid) or {}).get('displayName') or 'Macro'
        if ref.startswith('$@Generic___@MacroAdjustment___'):
            mid = ref.rsplit('___', 1)[-1]
            return (self.macro_adjustments.get(mid) or {}).get('displayName') or 'Adjustment'
        if ref.startswith('$@Generic___@ChangeWorkspace___'):
            old = ref.split('|')[-1]
            w = next((x for x in self.workspaces if x.get('name') == old), None)
            return (w or {}).get('displayName') or 'Workspace'
        if ref.startswith('$@Generic___@ChangeTouchPage___'):
            pid = ref.split('|')[-1]
            return (self.touch_pages_by_id.get(pid) or {}).get('displayName') or 'Page'
        if ref.startswith('$@Generic___@ChangeEncoderPage___'):
            pid = ref.split('|')[-1]
            return (self.encoder_pages_by_id.get(pid) or {}).get('displayName') or 'Dials'
        # Plugin-ish fallback: keep the final readable token.
        tail = ref.split('___')[-1]
        tail = urllib.parse.unquote(tail)
        return tail[:28]

    def _profile_action_command(self, action: dict[str, Any], context: dict[str, Any]) -> str | None:
        template = action.get('templateActionName') or ''
        params = ((action.get('actionParameters') or {}).get('parameters') or {})
        if template == '$@Generic___@KeyboardKey':
            combo = normalize_key_combo(params.get('keyboardKey'))
            if combo:
                return f'System.KeyCombination({combo})'
            return None
        if template == '$@Generic___@MouseClickExt':
            button = params.get('mouseButtonType') or 'Left'
            cmd = f'System.MouseClick({button})'
            if str(params.get('isDoubleClick', '')).lower() == 'true':
                return cmd + ' && ' + cmd
            keys = normalize_key_combo(params.get('keyboardKey'))
            if keys:
                return f'System.MouseCombo({keys},{button})'
            return cmd
        # MouseMoveExt is an adjustment with pointer-drag semantics; LoupixDeck has no direct
        # pointer-move command, so deliberately leave it unmapped.
        return None

    def _parse_execute_application(self, ref: str) -> str | None:
        prefix = '$@Generic___@ExecuteApplication___'
        if not ref.startswith(prefix):
            return None
        raw = ref[len(prefix):]
        target = raw.split('||||', 1)[0].strip().strip('"')
        if not target:
            return None
        return f'System.LaunchApp({command_encode(target)})'

    def _macro_command(self, macro: dict[str, Any], context: dict[str, Any], depth: int) -> str | None:
        local: dict[str, str] = {}
        for ed in macro.get('actionEditorCommands') or []:
            if ed.get('templateName') == '$@Generic___@KeyboardKey':
                combo = normalize_key_combo(((ed.get('actionParameters') or {}).get('keyboardKey')))
                if combo:
                    local[ed.get('name')] = f'System.KeyCombination({combo})'
        parts: list[str] = []
        for item in macro.get('actions') or []:
            if not item:
                continue
            if item in local:
                parts.append(local[item])
                continue
            cmd = self.resolve_action(item, context, depth=depth + 1, report_unsupported=False)
            if not cmd:
                return None
            parts.append(cmd)
        return ' && '.join(parts) if parts else None

    def resolve_action(self, ref: str | None, context: dict[str, Any], *, depth: int = 0,
                       report_unsupported: bool = True) -> str | None:
        if not ref or ref in ('$@Generic___@None', '@None'):
            return None
        if depth > 8:
            if report_unsupported:
                self._unsupported(ref, 'recursion-limit')
            return None

        cmd: str | None = None
        reason = 'unmapped-action'

        if ref.startswith('$@Generic___@ProfileAction___'):
            action = self.profile_actions.get(ref)
            if action:
                cmd = self._profile_action_command(action, context)
                if cmd is None:
                    reason = 'unsupported-profile-action:' + (action.get('templateActionName') or 'unknown')
            else:
                reason = 'missing-profile-action'

        elif ref.startswith('$@Generic___@Macro___'):
            mid = ref.rsplit('___', 1)[-1]
            macro = self.macro_commands.get(mid)
            if macro:
                cmd = self._macro_command(macro, context, depth)
                if cmd is None:
                    reason = 'unsupported-macro'
            else:
                reason = 'missing-macro'

        elif ref.startswith('$@Generic___@ChangeWorkspace___'):
            old_id = ref.split('|')[-1]
            new_id = self.workspace_guid_by_old.get(old_id)
            if new_id:
                cmd = f'System.GotoWorkspace({new_id})'
            else:
                reason = 'missing-workspace-target'

        elif ref.startswith('$@Generic___@ChangeTouchPage___'):
            parts = ref.split('|')
            target = parts[-1]
            source_workspace = parts[-2] if len(parts) >= 3 else None
            target_workspace = self.workspace_by_old.get(source_workspace) if source_workspace else None
            names = ((target_workspace or {}).get('touchPageNames') or
                     context.get('touch_page_names') or [])
            if target in names:
                page_cmd = f'System.GotoPage({names.index(target) + 1})'
                workspace_cmd = None
                if source_workspace:
                    new_wid = self.workspace_guid_by_old.get(source_workspace)
                    current_old = context.get('workspace_old_id')
                    if new_wid and source_workspace != current_old:
                        workspace_cmd = f'System.GotoWorkspace({new_wid})'
                cmd = f'{workspace_cmd} && {page_cmd}' if workspace_cmd else page_cmd
            else:
                reason = 'touch-page-target-outside-workspace'

        elif ref.startswith('$@Generic___@ChangeEncoderPage___'):
            parts = ref.split('|')
            target = parts[-1]
            source_workspace = parts[-2] if len(parts) >= 3 else None
            target_workspace = self.workspace_by_old.get(source_workspace) if source_workspace else None
            names = ((target_workspace or {}).get('encoderPageNames') or
                     context.get('encoder_page_names') or [])
            if target in names:
                n = names.index(target) + 1
                if self.target_side_strips:
                    page_cmd = f'System.GotoRotaryPageLeft({n}) && System.GotoRotaryPageRight({n})'
                else:
                    page_cmd = f'System.GotoRotaryPage({n})'
                workspace_cmd = None
                if source_workspace:
                    new_wid = self.workspace_guid_by_old.get(source_workspace)
                    current_old = context.get('workspace_old_id')
                    if new_wid and source_workspace != current_old:
                        workspace_cmd = f'System.GotoWorkspace({new_wid})'
                cmd = f'{workspace_cmd} && {page_cmd}' if workspace_cmd else page_cmd
            else:
                reason = 'rotary-page-target-outside-workspace'

        elif ref.startswith('$@Generic___@ExecuteApplication___'):
            cmd = self._parse_execute_application(ref)
            if cmd is None:
                reason = 'invalid-execute-application'

        elif ref == '$DefaultWin___MediaPlayPause':
            cmd = 'System.KeyCombination(PlayPause)'

        elif ref in ('$@Generic___@MouseClick',):
            cmd = 'System.MouseClick(Left)'

        if cmd:
            self.stats['mapped_actions'] += 1
            self._mark_command_names(cmd)
            return cmd

        if report_unsupported:
            self._unsupported(ref, reason)
        return None

    def resolve_rotary(self, press_ref: str | None, rotate_ref: str | None,
                       context: dict[str, Any]) -> tuple[str | None, str | None, str | None, str]:
        press = self.resolve_action(press_ref, context) if press_ref else None
        left = right = None
        label = self._label_for_ref(rotate_ref or press_ref)

        if not rotate_ref or rotate_ref in ('$@Generic___@None', '@None'):
            return left, right, press, label

        if rotate_ref.startswith('$@Generic___@MacroAdjustment___'):
            mid = rotate_ref.rsplit('___', 1)[-1]
            adj = self.macro_adjustments.get(mid)
            if adj:
                local: dict[str, str] = {}
                for ed in adj.get('actionEditorCommands') or []:
                    if ed.get('templateName') == '$@Generic___@KeyboardKey':
                        combo = normalize_key_combo(((ed.get('actionParameters') or {}).get('keyboardKey')))
                        if combo:
                            local[ed.get('name')] = f'System.KeyCombination({combo})'
                def side(items: list[str] | None) -> str | None:
                    parts: list[str] = []
                    for item in items or []:
                        if not item:
                            continue
                        if item in local:
                            parts.append(local[item])
                        else:
                            cmd = self.resolve_action(item, context, report_unsupported=False)
                            if not cmd:
                                return None
                            parts.append(cmd)
                    return ' && '.join(parts) if parts else None
                left = side(adj.get('actionsLeft'))
                right = side(adj.get('actionsRight'))
                if left or right:
                    self.stats['mapped_rotary_adjustments'] += 1
                    self._mark_command_names(left)
                    self._mark_command_names(right)
                else:
                    self._unsupported(rotate_ref, 'unsupported-rotary-adjustment')
            else:
                self._unsupported(rotate_ref, 'missing-rotary-adjustment')

        elif rotate_ref == '$DefaultWin___Volume':
            left = 'System.KeyCombination(VolumeDown)'
            right = 'System.KeyCombination(VolumeUp)'
            self._mark_command_names(left); self._mark_command_names(right)
            self.stats['mapped_rotary_adjustments'] += 1

        elif rotate_ref == '$@Generic___@MouseWheel':
            left = 'System.MouseScroll(-1)'
            right = 'System.MouseScroll(1)'
            self._mark_command_names(left); self._mark_command_names(right)
            self.stats['mapped_rotary_adjustments'] += 1

        else:
            # Some profile actions are adjustments, but pointer-move/drag has no direct core equivalent.
            self._unsupported(rotate_ref, 'unsupported-rotary-action')

        if (press_ref and press_ref not in ('$@Generic___@None', '@None') and not press) or (
            rotate_ref and rotate_ref not in ('$@Generic___@None', '@None') and not (left or right)
        ):
            label = ''
        return left, right, press, label

    def _button_layers(self, ref: str | None, label: str) -> list[dict[str, Any]]:
        if not ref or ref in ('$@Generic___@None', '@None'):
            return []
        if ref:
            layers = self._icon_layers(ref)
            if layers:
                return layers
        image = self._find_image(ref)
        if image:
            rel = self._import_asset(image)
            self.stats['icons_copied'] += 1
            return [image_layer(rel, label or 'Imported icon')]
        if label:
            return [text_layer(label)]
        return []

    def _convert_touch_page(self, src: dict[str, Any], page_num: int, context: dict[str, Any]) -> dict[str, Any]:
        controls = src.get('controls') or []
        buttons: list[dict[str, Any]] = []
        for i in range(self.target_touch_count):
            ref = (controls[i].get('pressAction') if i < len(controls) else None)
            command = self.resolve_action(ref, context) if ref else None
            label = self._label_for_ref(ref)
            unmapped = bool(ref and ref not in ('$@Generic___@None', '@None') and not command)
            if unmapped:
                short_label = label[:11] + '…' if len(label) > 12 else label
                caption = text_layer('Not imported\n' + short_label, 'Unmapped action')
                caption['TextSize'] = 10
                caption['BoxWidth'] = 84
                caption['BoxHeight'] = 84
                layers = [caption]
            else:
                layers = self._button_layers(ref, label) if ref else []
                if any(layer['kind'] == 'image' for layer in layers):
                    bottom_labels = [layer for layer in layers if layer['kind'] == 'text' and layer['PositionY'] >= 25]
                    for layer in bottom_labels:
                        layer['TextSize'] = max(12, layer['TextSize'])
                        layer['BoxHeight'] = 20
                        layer['PositionY'] = 27
                    if bottom_labels:
                        for layer in layers:
                            if layer['kind'] == 'image':
                                layer['Scale'] = min(layer['Scale'], .65)
                                layer['PositionY'] -= 10
            button = make_touch_button(i, command, layers)
            if unmapped:
                button['States'][0]['BackColor'] = '#54202B'
                button['States'][0]['BackgroundEnabled'] = True
            buttons.append(button)
            if ref and ref not in ('$@Generic___@None', '@None'):
                self.stats['touch_assignments_seen'] += 1
                if command:
                    self.stats['touch_assignments_mapped'] += 1
        return make_touch_page(src.get('displayName') or '', page_num, buttons)

    def _convert_encoder_page(self, src: dict[str, Any], page_num: int, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        controls = src.get('controls') or []
        # Loupedeck40 profiles contain six encoders. Razer Stream Controller uses two independent
        # columns of three, so split 0..2 and 3..5.
        all_rotaries: list[dict[str, Any]] = []
        for i in range(max(6, len(controls))):
            c = controls[i] if i < len(controls) else {}
            left, right, press, label = self.resolve_rotary(c.get('pressAction'), c.get('rotateAction'), context)
            local_index = i if i < 3 else i - 3
            all_rotaries.append(make_rotary_button(local_index, label, left, right, press))
            if c.get('pressAction') or c.get('rotateAction'):
                self.stats['rotary_assignments_seen'] += 1
                if press or left or right:
                    self.stats['rotary_assignments_partly_mapped'] += 1
        while len(all_rotaries) < 6:
            i = len(all_rotaries)
            all_rotaries.append(make_rotary_button(i if i < 3 else i - 3, '', None, None, None))
        name = src.get('displayName') or ''
        left_canvas = self._strip_canvas(controls[:3], 1) if self.target_side_strips else None
        right_canvas = self._strip_canvas(controls[3:6], 2) if self.target_side_strips else None
        return (
            make_rotary_page(name, page_num, 1, all_rotaries[:3], left_canvas),
            make_rotary_page(name, page_num, 2, all_rotaries[3:6], right_canvas),
        )

    def _strip_canvas(self, controls: list[dict[str, Any]], side: int) -> dict[str, Any] | None:
        contents: list[list[dict[str, Any]]] = []
        for control in controls:
            layers = []
            for ref in (control.get('rotateAction'), control.get('pressAction')):
                layers = self._button_layers(ref, '')
                if layers:
                    break
            contents.append(layers)
        if not any(contents):
            return None

        layers = []
        for i, source_layers in enumerate(contents):
            offset = (i - 1) * 90
            for layer in source_layers:
                if layer['kind'] == 'image':
                    layer['PositionX'] = round(layer['PositionX'] * 2 / 3)
                    layer['PositionY'] = round(layer['PositionY'] * 2 / 3 + offset - 15)
                else:
                    layer['BoxWidth'] = 58
                    layer['BoxHeight'] = 26
                    layer['TextSize'] = max(10, layer['TextSize'])
                    layer['PositionY'] = offset + 28
                layers.append(layer)
        return make_touch_button(12 if side == 1 else 13, None, layers)

    def _convert_simple_buttons(self, home_workspace_old: str | None) -> list[dict[str, Any]]:
        # Legacy Loupedeck/Razer profiles expose eight round LED buttons in roundPage.controls.
        # BUTTON0 commonly has no explicit action because the official app treats it as the Home
        # workspace key; preserve that behaviour using homeWorkspaceName.
        round_page = (self.profile.get('layout') or {}).get('roundPage') or {}
        controls = round_page.get('controls') or []
        buttons: list[dict[str, Any]] = []

        global_context = {
            'workspace_old_id': None,
            'touch_page_names': [],
            'encoder_page_names': [],
        }

        for i in range(8):
            ref = controls[i].get('pressAction') if i < len(controls) and controls[i] else None
            command = self.resolve_action(ref, global_context) if ref else None

            if i == 0 and not command and home_workspace_old:
                home_new = self.workspace_guid_by_old.get(home_workspace_old)
                if home_new:
                    command = f'System.GotoWorkspace({home_new})'
                    self._mark_command_names(command)
                    self.stats['simple_home_fallback'] += 1

            if ref and ref not in ('$@Generic___@None', '@None', ''):
                self.stats['simple_assignments_seen'] += 1
                if command:
                    self.stats['simple_assignments_mapped'] += 1

            buttons.append(make_simple_button(6 + i, command))

        return buttons

    def convert(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        converted_workspaces: list[dict[str, Any]] = []
        for w in self.workspaces:
            wid_old = w.get('name')
            touch_names = w.get('touchPageNames') or []
            encoder_names = w.get('encoderPageNames') or []
            context = {
                'workspace_old_id': wid_old,
                'touch_page_names': touch_names,
                'encoder_page_names': encoder_names,
            }
            touch_pages = []
            for n, pid in enumerate(touch_names, 1):
                src = self.touch_pages_by_id.get(pid)
                if not src:
                    self._unsupported(pid, 'missing-touch-page-definition')
                    continue
                touch_pages.append(self._convert_touch_page(src, n, context))

            left_pages: list[dict[str, Any]] = []
            right_pages: list[dict[str, Any]] = []
            shared_pages: list[dict[str, Any]] = []
            for n, pid in enumerate(encoder_names, 1):
                src = self.encoder_pages_by_id.get(pid)
                if not src:
                    self._unsupported(pid, 'missing-encoder-page-definition')
                    continue
                left, right = self._convert_encoder_page(src, n, context)
                if self.target_side_strips:
                    left_pages.append(left); right_pages.append(right)
                else:
                    # Recombine for non-side-strip targets.
                    combined = left.copy()
                    combined['Side'] = 0
                    combined['RotaryButtons'] = []
                    for i, b in enumerate((left['RotaryButtons'] + right['RotaryButtons'])):
                        bb = dict(b); bb['Index'] = i; combined['RotaryButtons'].append(bb)
                    shared_pages.append(combined)

            converted_workspaces.append({
                'Id': self.workspace_guid_by_old.get(wid_old, guid()),
                'Name': w.get('displayName') or 'Workspace',
                'StartupTouchPageIndex': 0,
                'RotaryButtonPages': shared_pages,
                'LeftRotaryButtonPages': left_pages,
                'RightRotaryButtonPages': right_pages,
                'TouchButtonPages': touch_pages,
            })

            wheel_names = w.get('wheelPageNames') or []
            if wheel_names:
                self.stats['wheel_pages_unmapped'] += len(wheel_names)

        # Prefer the explicit legacy homeWorkspaceName; fall back to a visible HOME/Main name.
        home_old = self.layout_mode.get('homeWorkspaceName')
        home = None
        if home_old:
            home_id = self.workspace_guid_by_old.get(home_old)
            home = next((w for w in converted_workspaces if w['Id'] == home_id), None)
        if home is None:
            home = next((w for w in converted_workspaces if w['Name'].strip().lower() in {'home', 'main', 'default'}), None)
        if home is None and converted_workspaces:
            home = converted_workspaces[0]
        if home_old is None and home:
            home_old = next((old for old, new in self.workspace_guid_by_old.items() if new == home['Id']), None)

        simple_buttons = self._convert_simple_buttons(home_old)

        profile_name = self.profile.get('displayName') or self.app.get('displayName') or self.lp5_path.stem
        target_profile = {
            'Id': guid(),
            'Name': profile_name,
            'Workspaces': converted_workspaces,
            'HomeWorkspaceId': home['Id'] if home else '00000000-0000-0000-0000-000000000000',
            'SimpleButtons': simple_buttons,
            'Priority': 0,
        }
        payload = {'Profile': target_profile}

        manifest = {
            'FormatVersion': 1,
            'ConfigSchemaVersion': int(self.template_manifest.get('ConfigSchemaVersion', 13)),
            'Kind': 'Profile',
            'Name': profile_name,
            'Description': f'Converted from {self.lp5_path.name} by lp5-to-loupix',
            'SourceDeviceSlug': self.template_manifest.get('SourceDeviceSlug', 'razer-stream-controller'),
            'SourceDeviceName': self.template_manifest.get('SourceDeviceName', 'Razer Stream Controller'),
            'SourceTouchButtonCount': self.target_touch_count,
            'SourceRotaryButtonCount': self.target_rotary_count,
            'SourceHasSideStrips': self.target_side_strips,
            'AppVersion': self.template_manifest.get('AppVersion', 'unknown'),
            'ExportedUtc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'RequiredPlugins': [],
            'ReferencedCommands': sorted(self.referenced_commands),
            'Assets': sorted(self.asset_paths),
            'Macros': [],
            'PayloadFile': 'payload.json',
        }

        report = {
            'input': self.lp5_path.name,
            'application': {
                'displayName': self.app.get('displayName'),
                'processOrBundleName': self.app.get('processOrBundleName'),
                'deviceType': self.app.get('deviceType'),
            },
            'profile': profile_name,
            'target': {
                'device': manifest['SourceDeviceName'],
                'touchButtons': self.target_touch_count,
                'rotaryButtons': self.target_rotary_count,
                'sideStrips': self.target_side_strips,
            },
            'counts': {
                'workspaces': len(converted_workspaces),
                'touchPages': sum(len(w['TouchButtonPages']) for w in converted_workspaces),
                'leftRotaryPages': sum(len(w['LeftRotaryButtonPages']) for w in converted_workspaces),
                'rightRotaryPages': sum(len(w['RightRotaryButtonPages']) for w in converted_workspaces),
                **dict(self.stats),
                'assets': len(self.asset_paths),
            },
            'unsupported': [
                {'reason': reason, 'count': count, 'example': self.unsupported_examples.get(reason)}
                for reason, count in self.unsupported.most_common()
            ],
            'notes': [
                'Loupedeck40 wheel pages have no direct Razer Stream Controller equivalent and are reported but not converted.'
                if self.stats.get('wheel_pages_unmapped') else None,
                'The two extra target touch slots are left blank; the original profile has 12 touch controls per page.'
                if self.target_touch_count > 12 else None,
                'Round LED buttons were imported from layout.roundPage; BUTTON0 falls back to the legacy Home workspace when its explicit action is empty.',
                f'{self.stats.get("icons_copied", 0)} image layer(s) reference {len(self.asset_paths)} packaged PNG asset(s).',
            ],
        }
        report['notes'] = [x for x in report['notes'] if x]
        return manifest, payload, report

    def write(self, out_path: Path, report_path: Path) -> dict[str, Any]:
        manifest, payload, report = self.convert()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            z.writestr('payload.json', json.dumps(payload, ensure_ascii=False, indent=2))
            for rel, data in sorted(self.asset_blobs.items()):
                z.writestr(rel, data)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Convert Logitech/Loupedeck .lp5 profiles to LoupixDeck .loupixprofile packages.')
    ap.add_argument('input', type=Path, help='Input .lp5 file')
    ap.add_argument('-o', '--output', type=Path, help='Output .loupixprofile path')
    ap.add_argument('--template', type=Path, help='Existing .loupixprofile used only to inherit target device/schema metadata')
    ap.add_argument('--report', type=Path, help='Conversion report JSON path')
    args = ap.parse_args()

    out = args.output or args.input.with_suffix('.loupixprofile')
    report_path = args.report or out.with_suffix('.conversion-report.json')

    try:
        c = Converter(args.input, args.template)
        report = c.write(out, report_path)
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1

    counts = report['counts']
    print(f"Converted: {args.input} -> {out}")
    print(f"Profile: {report['profile']}")
    print(f"Workspaces: {counts.get('workspaces', 0)}")
    print(f"Touch pages: {counts.get('touchPages', 0)}")
    print(f"Rotary pages L/R: {counts.get('leftRotaryPages', 0)}/{counts.get('rightRotaryPages', 0)}")
    print(f"Touch assignments mapped: {counts.get('touch_assignments_mapped', 0)}/{counts.get('touch_assignments_seen', 0)}")
    print(f"Rotary assignments partly mapped: {counts.get('rotary_assignments_partly_mapped', 0)}/{counts.get('rotary_assignments_seen', 0)}")
    print(f"Assets copied: {counts.get('assets', 0)}")
    unsupported_total = sum(x['count'] for x in report['unsupported'])
    print(f"Unsupported mappings: {unsupported_total}")
    print(f"Report: {report_path}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
