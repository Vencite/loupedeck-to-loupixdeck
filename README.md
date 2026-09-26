# lp5-to-loupix

A small converter from Logitech/Loupedeck `.lp5` profiles to [LoupixDeck](https://github.com/RadiatorTwo/LoupixDeck) `.loupixprofile` packages.

I wrote this for my own migration. I do not expect to develop it further now that the migration is done, but I am sharing it in case it helps someone else. Check the conversion report and test the imported profile before relying on it.

## What it converts

Both formats are ZIP archives containing JSON and assets. The converter reads `ApplicationInfo.json`, `ProfileInfo.json`, `ActionImages/`, and `ActionIcons/` from the `.lp5` file. It writes a LoupixDeck package with `manifest.json`, `payload.json`, and referenced `assets/`.

The current reference target is LoupixDeck 1.33.0 on a Razer Stream Controller: schema 13, 14 touch buttons, 6 encoders, and independent left and right encoder pages.

Supported conversions include:

- Workspaces and touch/rotary pages.
- The 12 legacy touch slots mapped to the first 12 of 14 target slots.
- Six encoders split into three left and three right controls.
- Encoder icons from `ActionIcons/` or `ActionImages/` on side-strip pages; pages with icons use LoupixDeck's FreeDraw strip mode and only retain text present in the source icon.
- Round LED buttons (`SimpleButtons`), including the implicit Home action on `BUTTON0`.
- Keyboard shortcuts, some macros, workspace/page navigation, application launch, mouse click and wheel, media play/pause, and volume.
- PNG images from `ActionImages/` and embedded PNG or SVG icons and visible text from `ActionIcons/*.ict`. SVG rasterization requires `ffmpeg` in `PATH`.

Unknown actions and plugins are never guessed. Unmapped touch buttons receive a dark red background and compact “Not imported” label. Unsupported encoder actions remain visible in the `*.conversion-report.json` file without adding text to the side strip.

## Usage

Requires Python 3.11+. The Python code uses only the standard library; `ffmpeg` is optional for SVG icons.

```bash
python3 lp5_to_loupix.py profile.lp5 \
  --template Home.loupixprofile \
  -o profile.loupixprofile
```

`--template` is optional. It inherits target device and schema metadata from a real LoupixDeck export, without copying that export's profile content.

The converter also writes `profile.conversion-report.json` next to the output by default.

Profiles and conversion reports can contain personal configuration. Review them before sharing; this repository does not include example profiles.

## Known gaps

- `MouseMoveExt` pointer dragging has no confirmed native LoupixDeck equivalent.
- Legacy `wheelPages` have no direct equivalent on the Razer Stream Controller.
- Plugin-specific actions need explicit mappings backed by known target command semantics.
- SVG icons need `ffmpeg`; unavailable or unreadable icon images are reported as unsupported.
- Screenshots of a real LoupixDeck import confirm that some icons render. SVG icons are now rasterized at 240×240 to avoid enlarging 32×32 source renders; the improved result still needs a real import check. Low-resolution bitmap source icons cannot gain detail through this change.
