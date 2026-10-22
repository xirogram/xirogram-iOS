#!/usr/bin/env python3
"""
configure_xirogram.py - Configures Telegram iOS (xirogram-iOS) for a private MTProto server.
Applies:
- Custom App Name
- Custom App Icon (from any image format: PNG, JPG, WebP, SVG, GIF, HEIC, etc.)
- Custom Server IP & Port (both MTProto datacenter overrides and seed addresses)
- Custom Server MTProto RSA Public Key
- Custom or Default API ID & API Hash
- Custom Bundle ID (with automatic re-signing of fake provisioning profiles)
- Custom Domain Everywhere (link parsing, preview, whitelist, universal links)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.sax.saxutils
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def get_required(name: str) -> str:
    val = os.environ.get(name, '').strip()
    if not val:
        print(f"Error: missing required environment variable '{name}'", file=sys.stderr)
        sys.exit(1)
    return val

def get_optional(name: str, default: str) -> str:
    val = os.environ.get(name, '').strip()
    return val if val else default

def sanitize_domain(d: str) -> str:
    clean = d.strip()
    if clean.startswith('https://'):
        clean = clean[len('https://'):]
    elif clean.startswith('http://'):
        clean = clean[len('http://'):]
    return clean.rstrip('/')

def convert_and_apply_icons(avatar_url: str):
    clean_path = avatar_url.strip().strip("'\"")
    if clean_path.startswith("file://"):
        clean_path = clean_path[len("file://"):]
    local_path = Path(os.path.expanduser(clean_path))

    if local_path.is_file():
        print(f"[*] Reading local app icon from: {local_path}")
        raw_bytes = local_path.read_bytes()
    else:
        print(f"[*] Downloading app icon from: {avatar_url}")
        req = urllib.request.Request(
            avatar_url,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
                raw_bytes = resp.read()
        except Exception as e:
            print(f"[!] urllib download failed ({e}), falling back to curl...")
            res = subprocess.run(["curl", "-sSLk", avatar_url], capture_output=True, check=True)
            raw_bytes = res.stdout

    with tempfile.TemporaryDirectory() as td:
        raw_file = Path(td) / "raw_avatar"
        raw_file.write_bytes(raw_bytes)

        master_png = Path(td) / "master.png"

        # Check for ImageMagick first (handles SVG, WebP, AVIF, HEIC, JPG, PNG, GIF)
        has_magick = shutil.which("magick") is not None
        has_sips = shutil.which("sips") is not None

        converted = False
        if has_magick:
            try:
                subprocess.run(
                    ["magick", f"{raw_file}[0]", "-strip", str(master_png)],
                    check=True,
                    capture_output=True
                )
                converted = True
            except Exception as e:
                print(f"[!] Warning: ImageMagick failed: {e}. Trying fallback...")

        if not converted and has_sips:
            try:
                subprocess.run(
                    ["sips", "-s", "format", "png", str(raw_file), "--out", str(master_png)],
                    check=True,
                    capture_output=True
                )
                converted = True
            except Exception as e:
                print(f"[!] Warning: sips failed: {e}. Trying fallback...")

        if not converted:
            try:
                from PIL import Image
                with Image.open(raw_file) as im:
                    im.convert("RGBA").save(master_png, "PNG")
                converted = True
            except Exception as e:
                print(f"[!] Warning: PIL failed: {e}")

        if not converted or not master_png.exists():
            raise SystemExit("Failed to convert avatar to PNG. Ensure ImageMagick, sips, or Pillow is available.")

        # Target asset catalogs to update
        catalogs = [
            ROOT / "Telegram/Telegram-iOS/AppIcons.xcassets/BlueIcon.appiconset",
            ROOT / "Telegram/Telegram-iOS/AppIcons.xcassets/BlueFilledIcon.appiconset",
            ROOT / "Telegram/Telegram-iOS/AppIcons.xcassets/BlackIcon.appiconset",
            ROOT / "Telegram/Telegram-iOS/AppIcons.xcassets/BlackFilledIcon.appiconset",
            ROOT / "Telegram/Telegram-iOS/DefaultAppIcon.xcassets/AppIconLLC.appiconset"
        ]

        for cat_dir in catalogs:
            contents_file = cat_dir / "Contents.json"
            if not contents_file.exists():
                continue
            cat_data = json.loads(contents_file.read_text())
            modified_contents = False
            for img_entry in cat_data.get("images", []):
                # 76x76@1x causes actool error in Xcode 16/26 with iOS 15+ target
                if img_entry.get("size") == "76x76" and img_entry.get("scale") == "1x" and img_entry.get("idiom") == "ipad":
                    old_fn = img_entry.pop("filename", None)
                    if old_fn:
                        old_file = cat_dir / old_fn
                        if old_file.exists():
                            old_file.unlink()
                        modified_contents = True

                # Ensure 1024x1024 marketing icon has a filename
                if img_entry.get("size") == "1024x1024" and img_entry.get("idiom") == "ios-marketing":
                    if not img_entry.get("filename"):
                        img_entry["filename"] = "IconMarketing@1024x1024.png"
                        modified_contents = True

            if modified_contents:
                contents_file.write_text(json.dumps(cat_data, indent=2))

            for img_entry in cat_data.get("images", []):
                fn = img_entry.get("filename")
                if not fn:
                    continue
                size_str = img_entry.get("size", "60x60")
                w_pt, h_pt = [float(x) for x in size_str.split("x")]
                scale_str = img_entry.get("scale", "1x").replace("x", "")
                scale = float(scale_str)
                target_w = int(round(w_pt * scale))
                target_h = int(round(h_pt * scale))

                target_path = cat_dir / fn

                if has_magick:
                    subprocess.run(
                        ["magick", str(master_png), "-resize", f"{target_w}x{target_h}!", str(target_path)],
                        check=True
                    )
                elif has_sips:
                    subprocess.run(
                        ["sips", "-z", str(target_h), str(target_w), str(master_png), "--out", str(target_path)],
                        check=True,
                        capture_output=True
                    )
                else:
                    from PIL import Image
                    with Image.open(master_png) as im:
                        im.resize((target_w, target_h), Image.Resampling.LANCZOS).save(target_path, "PNG")

        print("[*] Successfully generated all AppIcon sizes.")

def resign_fake_provisioning_profiles(bundle_id: str):
    profiles_dir = ROOT / "build-system/fake-codesigning/profiles"
    cert_p12 = ROOT / "build-system/fake-codesigning/certs/SelfSigned.p12"

    if not profiles_dir.exists() or not cert_p12.exists():
        print("[!] Warning: fake-codesigning profiles or certs not found, skipping profile resigning.")
        return

    print(f"[*] Resigning fake provisioning profiles for bundle ID '{bundle_id}'...")
    with tempfile.TemporaryDirectory() as td:
        pem_path = Path(td) / "combined.pem"

        # Extract cert and private key from SelfSigned.p12
        res = subprocess.run(
            ["openssl", "pkcs12", "-legacy", "-in", str(cert_p12), "-passin", "pass:", "-nodes", "-out", str(pem_path)],
            capture_output=True
        )
        if res.returncode != 0:
            subprocess.run(
                ["openssl", "pkcs12", "-in", str(cert_p12), "-passin", "pass:", "-nodes", "-out", str(pem_path)],
                check=True
            )

        for prof in profiles_dir.glob("*.mobileprovision"):
            plist_bytes = subprocess.check_output(
                ["openssl", "smime", "-inform", "der", "-verify", "-noverify", "-in", str(prof)],
                stderr=subprocess.DEVNULL
            )
            updated_text = plist_bytes.decode("latin1").replace("ph.telegra.Telegraph", bundle_id)

            plist_temp = Path(td) / "temp.plist"
            plist_temp.write_bytes(updated_text.encode("latin1"))

            subprocess.run(
                [
                    "openssl", "smime", "-sign",
                    "-in", str(plist_temp),
                    "-out", str(prof),
                    "-outform", "DER",
                    "-signer", str(pem_path),
                    "-inkey", str(pem_path),
                    "-nodetach"
                ],
                check=True
            )
    print("[*] Resigned all fake provisioning profiles.")

def configure_network(server_ip: str, server_port: str):
    net_path = ROOT / "submodules/TelegramCore/Sources/Network/Network.swift"
    content = net_path.read_text()

    # 1. Set datacenterAddressOverrides for DC 1 through 5
    needle = "            apiEnvironment.apiId = arguments.apiId\n"
    dc_overrides = (
        f"            apiEnvironment.datacenterAddressOverrides = [\n"
        f"                NSNumber(value: 1): MTDatacenterAddress(ip: \"{server_ip}\", port: {server_port}, preferForMedia: false, restrictToTcp: true, cdn: false, preferForProxy: false, secret: nil),\n"
        f"                NSNumber(value: 2): MTDatacenterAddress(ip: \"{server_ip}\", port: {server_port}, preferForMedia: false, restrictToTcp: true, cdn: false, preferForProxy: false, secret: nil),\n"
        f"                NSNumber(value: 3): MTDatacenterAddress(ip: \"{server_ip}\", port: {server_port}, preferForMedia: false, restrictToTcp: true, cdn: false, preferForProxy: false, secret: nil),\n"
        f"                NSNumber(value: 4): MTDatacenterAddress(ip: \"{server_ip}\", port: {server_port}, preferForMedia: false, restrictToTcp: true, cdn: false, preferForProxy: false, secret: nil),\n"
        f"                NSNumber(value: 5): MTDatacenterAddress(ip: \"{server_ip}\", port: {server_port}, preferForMedia: false, restrictToTcp: true, cdn: false, preferForProxy: false, secret: nil)\n"
        f"            ]\n"
    )

    if "apiEnvironment.datacenterAddressOverrides" not in content:
        content = content.replace(needle, needle + dc_overrides, 1)

    # 2. Update seed addresses and default port
    seed_pattern = re.compile(r'let seedAddressList:\s*\[Int:\s*\[String\]\]\s*if testingEnvironment\s*\{.*?\}\s*else\s*\{.*?\}', re.DOTALL)
    new_seed = (
        f'let seedAddressList: [Int: [String]] = [\n'
        f'                1: ["{server_ip}"],\n'
        f'                2: ["{server_ip}"],\n'
        f'                3: ["{server_ip}"],\n'
        f'                4: ["{server_ip}"],\n'
        f'                5: ["{server_ip}"]\n'
        f'            ]'
    )
    content = seed_pattern.sub(lambda m: new_seed, content)

    content = content.replace(
        'MTDatacenterAddress(ip: $0, port: 443,',
        f'MTDatacenterAddress(ip: $0, port: {server_port},'
    )

    net_path.write_text(content)
    print(f"[*] Configured network endpoints for server {server_ip}:{server_port}")

def configure_rsa_key(rsa_key: str):
    auth_service_path = ROOT / "submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m"
    content = auth_service_path.read_text()

    clean_key = rsa_key.strip().replace("\r\n", "\n").replace("\\n", "\n")
    lines = [line.strip() for line in clean_key.splitlines() if line.strip()]
    objc_key_lines = "\n            ".join([f'@"{l}\\n"' for l in lines])

    replacement_keys = (
        f"        productionPublicKeys = @[\n"
        f"            [[MTDatacenterAuthPublicKey alloc] initWithPublicKey:\n"
        f"            {objc_key_lines}\n"
        f"            ]\n"
        f"        ];\n"
        f"        testingPublicKeys = productionPublicKeys;\n"
    )

    pattern = re.compile(
        r'dispatch_once\(&onceToken,\s*\^\{\s*testingPublicKeys\s*=\s*@\[.*?\];\s*productionPublicKeys\s*=\s*@\[.*?\];\s*\}\);',
        re.DOTALL
    )

    new_dispatch_block = (
        f"dispatch_once(&onceToken, ^{{\n"
        f"{replacement_keys}"
        f"    }});"
    )

    new_content, count = pattern.subn(lambda m: new_dispatch_block, content)
    if count == 0:
        print("[!] Warning: could not regex replace defaultPublicKeys in MTDatacenterAuthMessageService.m; attempting fallback replace")
        idx = content.find("static NSArray<MTDatacenterAuthPublicKey *> *defaultPublicKeys(bool isProduction) {")
        if idx != -1:
            end_idx = content.find("if (isProduction) {", idx)
            if end_idx != -1:
                content = content[:idx] + (
                    "static NSArray<MTDatacenterAuthPublicKey *> *defaultPublicKeys(bool isProduction) {\n"
                    "    static NSArray<MTDatacenterAuthPublicKey *> *testingPublicKeys = nil;\n"
                    "    static NSArray<MTDatacenterAuthPublicKey *> *productionPublicKeys = nil;\n"
                    "    static dispatch_once_t onceToken;\n"
                    f"{new_dispatch_block}\n    "
                ) + content[end_idx:]
                new_content = content
    auth_service_path.write_text(new_content)
    print("[*] Configured custom MTProto RSA public key.")

def configure_app_name(app_name: str):
    escaped_name = xml.sax.saxutils.escape(app_name)

    # 1. Telegram/BUILD
    build_path = ROOT / "Telegram/BUILD"
    build_content = build_path.read_text()
    build_content = build_content.replace("<string>Telegram</string>", f"<string>{escaped_name}</string>")
    build_path.write_text(build_content)

    # 2. Info.plist & InfoBazel.plist
    for p in [ROOT / "Telegram/Telegram-iOS/Info.plist", ROOT / "Telegram/Telegram-iOS/InfoBazel.plist"]:
        if p.exists():
            s = p.read_text()
            s = s.replace("<string>${APP_NAME}</string>", f"<string>{escaped_name}</string>")
            p.write_text(s)

    # 3. Localized strings (ar, ko)
    for p in [ROOT / "Telegram/Telegram-iOS/ar.lproj/InfoPlist.strings", ROOT / "Telegram/Telegram-iOS/ko.lproj/InfoPlist.strings"]:
        if p.exists():
            p.write_text(f'"CFBundleDisplayName" = "{app_name}";\n')

    print(f"[*] Configured app name to '{app_name}'")

def configure_domain(domain: str):
    # 1. UrlHandling.swift
    url_handling_path = ROOT / "submodules/UrlHandling/Sources/UrlHandling.swift"
    s = url_handling_path.read_text()
    if f'"{domain}"' not in s:
        s = s.replace(
            'private let baseTelegramMePaths = [',
            f'private let baseTelegramMePaths = [\n    "{domain}",'
        )
        s = s.replace(
            'private let telegramWebShortLinkHosts = [',
            f'private let telegramWebShortLinkHosts = [\n    "{domain}",'
        )
        url_handling_path.write_text(s)

    # 2. OpenUrl.swift
    open_url_path = ROOT / "submodules/TelegramUI/Sources/OpenUrl.swift"
    if open_url_path.exists():
        s = open_url_path.read_text()
        if f'"{domain}"' not in s:
            s = s.replace(
                'private let telegramMeHosts: [String] = ["t.me", "telegram.me", "telegram.dog"]',
                f'private let telegramMeHosts: [String] = ["t.me", "telegram.me", "telegram.dog", "{domain}"]'
            )
            open_url_path.write_text(s)

    # 3. GenerateTextEntities.swift
    gen_text_path = ROOT / "submodules/TextFormat/Sources/GenerateTextEntities.swift"
    if gen_text_path.exists():
        s = gen_text_path.read_text()
        if f'"{domain}"' not in s:
            s = s.replace(
                'private let whitelistedHosts: Set<String> = Set([',
                f'private let whitelistedHosts: Set<String> = Set([\n    "{domain}",'
            )
            gen_text_path.write_text(s)

    # 4. UrlWhitelist.swift
    whitelist_path = ROOT / "submodules/UrlWhitelist/Sources/UrlWhitelist.swift"
    if whitelist_path.exists():
        s = whitelist_path.read_text()
        if f'"{domain}"' not in s:
            s = s.replace(
                'private let whitelistedHosts: Set<String> = Set([',
                f'private let whitelistedHosts: Set<String> = Set([\n    "{domain}",'
            )
            whitelist_path.write_text(s)

    # 5. ChatControllerOpenLinkContextMenu.swift
    link_menu_path = ROOT / "submodules/TelegramUI/Sources/Chat/ChatControllerOpenLinkContextMenu.swift"
    if link_menu_path.exists():
        s = link_menu_path.read_text()
        old_check = 'if host == "t.me" || host == "telegram.me" || host == "telegram.dog" {'
        new_check = f'if host == "t.me" || host == "telegram.me" || host == "telegram.dog" || host == "{domain}" {{'
        if old_check in s:
            link_menu_path.write_text(s.replace(old_check, new_check, 1))

    # 6. Associated domains in Telegram/BUILD
    build_path = ROOT / "Telegram/BUILD"
    build_content = build_path.read_text()
    old_assoc = """associated_domains_fragment = "" if telegram_bundle_id not in official_bundle_ids else \"\"\"
<key>com.apple.developer.associated-domains</key>
<array>
    <string>applinks:telegram.me</string>
    <string>applinks:t.me</string>
    <string>applinks:*.t.me</string>
    <string>webcredentials:t.me</string>
    <string>webcredentials:telegram.org</string>
</array>
\"\"\""""

    new_assoc = f"""associated_domains_fragment = \"\"\"
<key>com.apple.developer.associated-domains</key>
<array>
    <string>applinks:telegram.me</string>
    <string>applinks:t.me</string>
    <string>applinks:*.t.me</string>
    <string>webcredentials:t.me</string>
    <string>webcredentials:telegram.org</string>
    <string>applinks:{domain}</string>
    <string>applinks:*.{domain}</string>
    <string>webcredentials:{domain}</string>
</array>
\"\"\""""
    if old_assoc in build_content:
        build_content = build_content.replace(old_assoc, new_assoc, 1)
        build_path.write_text(build_content)

    print(f"[*] Configured domain '{domain}' across all link handlers and associated domains.")

def configure_build_files(bundle_id: str, api_id: str, api_hash: str, domain: str):
    url_scheme = re.sub(r'[^a-zA-Z0-9]', '', domain.split('.')[0]) or "tg"

    config_data = {
        "bundle_id": bundle_id,
        "api_id": api_id,
        "api_hash": api_hash,
        "team_id": "C67CF9S4VU",
        "app_center_id": "0",
        "is_internal_build": "false",
        "is_appstore_build": "true",
        "appstore_id": "686449807",
        "app_specific_url_scheme": url_scheme,
        "premium_iap_product_id": "",
        "enable_siri": False,
        "enable_icloud": False
    }

    (ROOT / "build-system/appstore-configuration.json").write_text(json.dumps(config_data, indent=2) + "\n")
    (ROOT / "build-system/xirogram-configuration.json").write_text(json.dumps(config_data, indent=2) + "\n")

    build_path = ROOT / "Telegram/BUILD"
    build_content = build_path.read_text()

    # 1. Ensure DefaultIcon srcs include Contents.json and subfiles
    build_content = build_content.replace(
        '"Telegram-iOS/AppIcons.xcassets/BlueIcon.appiconset/*.png",',
        '"Telegram-iOS/AppIcons.xcassets/BlueIcon.appiconset/**",'
    )

    # 2. Switch app_icons to DefaultIcon
    old_app_icons = 'app_icons = [ ":{}_icon".format(name) for name in composer_icon_folders ],'
    new_app_icons = 'app_icons = [":DefaultIcon"],'
    if old_app_icons in build_content:
        build_content = build_content.replace(old_app_icons, new_app_icons, 1)

    build_path.write_text(build_content)
    print(f"[*] Configured build-system configuration files for bundle ID '{bundle_id}'")

def main():
    print("=== Xirogram iOS Configuration Script ===")
    app_name = get_required("APP_NAME")
    avatar_url = get_required("AVATAR_URL")
    server_ip = get_required("SERVER_IP")
    server_port = get_required("SERVER_PORT")
    rsa_public_key = get_required("RSA_PUBLIC_KEY")
    bundle_id = get_required("BUNDLE_ID")
    raw_domain = get_required("DOMAIN")

    domain = sanitize_domain(raw_domain)
    api_id = get_optional("API_ID", "8")
    api_hash = get_optional("API_HASH", "7245de8e747a0d6fbe11f7cc14fcc0bb")

    # Validation
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", bundle_id):
        print(f"Error: BUNDLE_ID '{bundle_id}' is invalid. Example: com.example.telegram", file=sys.stderr)
        sys.exit(1)

    if not server_port.isdigit() or not (1 <= int(server_port) <= 65535):
        print(f"Error: SERVER_PORT '{server_port}' must be an integer between 1 and 65535", file=sys.stderr)
        sys.exit(1)

    if "BEGIN RSA PUBLIC KEY" not in rsa_public_key and "BEGIN PUBLIC KEY" not in rsa_public_key:
        print("Error: RSA_PUBLIC_KEY must be in PEM format ('BEGIN RSA PUBLIC KEY' or 'BEGIN PUBLIC KEY')", file=sys.stderr)
        sys.exit(1)

    print(f"App Name: {app_name}")
    print(f"Bundle ID: {bundle_id}")
    print(f"Server: {server_ip}:{server_port}")
    print(f"Domain: {domain}")
    print(f"API ID: {api_id}")

    configure_build_files(bundle_id, api_id, api_hash, domain)
    configure_app_name(app_name)
    configure_network(server_ip, server_port)
    configure_rsa_key(rsa_public_key)
    configure_domain(domain)
    resign_fake_provisioning_profiles(bundle_id)
    convert_and_apply_icons(avatar_url)

    print("\n[✓] All configurations applied successfully!")

if __name__ == "__main__":
    main()
