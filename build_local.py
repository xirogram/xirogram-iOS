#!/usr/bin/env python3
"""
build_local.py - Interactive macOS local builder for Telegram iOS (xirogram-iOS).
Prompts user for all required parameters, applies custom MTProto configuration,
and compiles a sideloadable IPA locally on macOS.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ANSI color codes
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(text: str):
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}{BOLD}{text.center(60)}{RESET}")
    print(f"{CYAN}{'='*60}{RESET}\n")

def prompt_input(title: str, prompt: str, default: str = "", required: bool = True) -> str:
    print(f"{BOLD}{title}:{RESET}")
    if default:
        p_text = f"  {prompt} [{default}]: "
    else:
        p_text = f"  {prompt}: "

    while True:
        val = input(p_text).strip()
        if not val and default:
            return default
        if not val and required:
            print(f"  {RED}Поле обязательно для заполнения! Попробуйте снова.{RESET}")
            continue
        return val

def prompt_rsa_key() -> str:
    print(f"{BOLD}6. MTProto RSA публичный ключ сервера (PEM):{RESET}")
    print(f"  {YELLOW}Подсказка: Вставьте путь к файлу .pem (можно перетащить файл сюда){RESET}")
    print(f"  {YELLOW}ИЛИ просто скопируйте и вставьте текст ключа (включая -----BEGIN/END...):{RESET}")

    first_line = input("  Ключ или путь к файлу: ").strip()
    clean_path = first_line.strip("'\"")
    if clean_path.startswith("file://"):
        clean_path = clean_path[len("file://"):]
    local_file = Path(os.path.expanduser(clean_path))

    if local_file.is_file():
        content = local_file.read_text().strip()
        print(f"  {GREEN}✓ Считан ключ из файла: {local_file}{RESET}")
        return content

    # Check if user entered multiline or first line of PEM
    lines = [first_line]
    if "-----END" not in first_line:
        while True:
            try:
                line = input()
            except EOFError:
                break
            lines.append(line)
            if "-----END" in line:
                break

    # Clean lines and filter out any accidental 'EOF'
    cleaned_lines = [l.strip() for l in lines if l.strip() and l.strip().upper() != "EOF"]
    key_text = "\n".join(cleaned_lines).strip()
    if not key_text:
        print(f"  {RED}Ошибка: RSA ключ не может быть пустым!{RESET}")
        return prompt_rsa_key()
    return key_text

def run_cmd(cmd, cwd=ROOT, check=True):
    print(f"{CYAN}> {' '.join(str(c) for c in cmd)}{RESET}")
    res = subprocess.run(cmd, cwd=cwd)
    if check and res.returncode != 0:
        print(f"\n{RED}Ошибка выполнения команды (код {res.returncode}){RESET}")
        sys.exit(res.returncode)
    return res

def main():
    print_header("Локальный билдер iOS Telegram для приватных серверов")

    # 1. Interactive questionnaire
    app_name = prompt_input(
        "1. Название приложения",
        "Введите имя приложения на рабочем столе",
        default="MyTelegram"
    )

    avatar = prompt_input(
        "2. Иконка / Аватарка",
        "Введите прямую ссылку (URL) или путь к файлу на компьютере (PNG, JPG, SVG, WebP...)",
        default="https://telegram.org/img/t_logo.png"
    )

    server_ip = prompt_input(
        "3. IP-адрес приватного сервера",
        "Введите IP-адрес сервера (e.g. 192.168.1.100 или 95.163...)"
    )

    server_port = prompt_input(
        "4. Порт сервера",
        "Введите порт сервера MTProto",
        default="443"
    )

    server_dc = prompt_input(
        "5. Номер дата-центра (DC ID)",
        "Введите ID дата-центра (обычно 1 или 2)",
        default="2"
    )

    rsa_key = prompt_rsa_key()

    api_id = prompt_input(
        "7. API ID (опционально)",
        "Введите числовой API ID (или Enter для дефолтного)",
        default="8",
        required=False
    )

    api_hash = prompt_input(
        "8. API Hash (опционально)",
        "Введите API Hash (или Enter для дефолтного)",
        default="7245de8e747a0d6fbe11f7cc14fcc0bb",
        required=False
    )

    bundle_id = prompt_input(
        "9. Bundle ID",
        "Введите уникальный идентификатор приложения",
        default="ph.telegra.Telegraph"
    )

    domain = prompt_input(
        "10. Домен для ссылок",
        "Введите домен (например, t.me или mydomain.com)",
        default="t.me"
    )

    # Summary
    print_header("Параметры сборки")
    print(f"  {BOLD}Название:{RESET}      {app_name}")
    print(f"  {BOLD}Аватар:{RESET}        {avatar}")
    print(f"  {BOLD}Сервер:{RESET}        {server_ip}:{server_port} (DC {server_dc})")
    print(f"  {BOLD}Bundle ID:{RESET}     {bundle_id}")
    print(f"  {BOLD}Домен:{RESET}         {domain}")
    print(f"  {BOLD}API ID / Hash:{RESET} {api_id} / {api_hash[:8]}...")
    print(f"  {BOLD}RSA Key:{RESET}       {rsa_key.splitlines()[0]}... ({len(rsa_key)} байт)")

    confirm = input(f"\n{YELLOW}Начать сборку? [Y/n]: {RESET}").strip().lower()
    if confirm not in ("", "y", "yes", "да"):
        print("Сборка отменена.")
        sys.exit(0)

    # 2. Pre-flight checks
    print_header("Проверка окружения macOS")

    # Check Xcode
    try:
        xcode_res = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True, check=True)
        print(f"{GREEN}✓ Обнаружен Xcode:{RESET}\n  {xcode_res.stdout.strip()}")
    except Exception:
        print(f"{RED}Ошибка: Xcode не установлен или не настроен через xcode-select.{RESET}")
        print("Выполните: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer")
        sys.exit(1)

    # Check git submodules
    print(f"[*] Проверка Git-субмодулей...")
    run_cmd(["git", "submodule", "update", "--init", "--recursive"])

    # 3. Apply custom configuration
    print_header("Применение конфигурации сервера и брендинга")
    env = os.environ.copy()
    env["APP_NAME"] = app_name
    env["AVATAR_URL"] = avatar
    env["SERVER_IP"] = server_ip
    env["SERVER_PORT"] = server_port
    env["SERVER_DC"] = server_dc
    env["RSA_PUBLIC_KEY"] = rsa_key
    env["API_ID"] = api_id
    env["API_HASH"] = api_hash
    env["BUNDLE_ID"] = bundle_id
    env["DOMAIN"] = domain

    config_script = ROOT / "scripts/configure_xirogram.py"
    subprocess.run([sys.executable, str(config_script)], env=env, cwd=ROOT, check=True)

    # 4. Import certificates & setup build number
    print_header("Подготовка сертификатов и сборка Bazel")
    certs_script = ROOT / "build-system/Make/ImportCertificates.py"
    run_cmd([sys.executable, str(certs_script), "--path", "build-system/fake-codesigning/certs"])

    # Version and build number
    versions_file = ROOT / "versions.json"
    versions_data = json.loads(versions_file.read_text())
    app_version = versions_data.get("app", "13.0")

    try:
        rev_count = subprocess.run(["git", "rev-list", "--count", "HEAD"], capture_output=True, text=True, check=True)
        commit_count = int(rev_count.stdout.strip())
    except Exception:
        commit_count = 1

    offset_file = ROOT / "build_number_offset"
    offset = int(offset_file.read_text().strip()) if offset_file.exists() else 0
    build_number = str(commit_count + offset)

    print(f"[*] App Version:  {app_version}")
    print(f"[*] Build Number: {build_number}")

    # 5. Build with Make.py
    print(f"[*] Запуск компиляции через Make.py (это займет некоторое время)...")
    make_script = ROOT / "build-system/Make/Make.py"
    bazel_user_root = "/private/var/tmp/_bazel_containerhost"

    build_cmd = [
        sys.executable, "-u", str(make_script),
        f"--bazelUserRoot={bazel_user_root}",
        "--overrideXcodeVersion",
        "build",
        "--configurationPath=build-system/appstore-configuration.json",
        "--codesigningInformationPath=build-system/fake-codesigning",
        "--configuration=release_arm64",
        f"--buildNumber={build_number}"
    ]

    run_cmd(build_cmd)

    # 6. Locate and collect output IPA
    print_header("Сборка завершена! Поиск готового IPA")

    output_dir = ROOT / "build/artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', app_name).strip() or "Telegram"
    final_ipa_path = output_dir / f"{safe_name}.ipa"

    found_ipa = None
    possible_paths = [
        ROOT / "bazel-bin/Telegram/Telegram.ipa",
        *ROOT.glob("bazel-out/applebin_ios-ios_arm*-opt-ST-*/bin/Telegram/Telegram.ipa")
    ]

    for p in possible_paths:
        if p.is_file():
            found_ipa = p
            break

    if not found_ipa:
        print(f"{RED}Ошибка: не удалось найти скомпилированный файл Telegram.ipa в bazel-bin!{RESET}")
        sys.exit(1)

    shutil.copyfile(found_ipa, final_ipa_path)
    file_size_mb = final_ipa_path.stat().st_size / (1024 * 1024)

    print(f"\n{GREEN}{BOLD}🎉 ГОТОВО! IPA успешно создан:{RESET}")
    print(f"  {BOLD}Файл:{RESET}    {final_ipa_path}")
    print(f"  {BOLD}Размер:{RESET}  {file_size_mb:.1f} MB")
    print(f"  {BOLD}Версия:{RESET}  {app_version} ({build_number})")

    # Collect dSYMs if present
    dsym_dir = ROOT / "build/DSYMs"
    dsym_dir.mkdir(parents=True, exist_ok=True)
    for dsym in [*ROOT.glob("bazel-bin/Telegram/*.dSYM"), *ROOT.glob("bazel-out/applebin_ios-ios_arm*-opt-ST-*/bin/Telegram/*.dSYM")]:
        if dsym.is_dir():
            target_dsym = dsym_dir / dsym.name
            if target_dsym.exists():
                shutil.rmtree(target_dsym)
            shutil.copytree(dsym, target_dsym)

    dsym_zip = output_dir / f"{safe_name}.DSYMs.zip"
    subprocess.run(["zip", "-r", str(dsym_zip), "build/DSYMs"], cwd=ROOT, capture_output=True)
    if dsym_zip.exists():
        print(f"  {BOLD}Символы dSYM:{RESET} {dsym_zip}")

    print(f"\n{CYAN}Открываем папку с готовым файлом в Finder...{RESET}")
    subprocess.run(["open", str(output_dir)])

if __name__ == "__main__":
    main()
