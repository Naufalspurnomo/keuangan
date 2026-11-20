#!/usr/bin/env python3
"""Deploy a narrow, CSS-only bilingual language-switcher UX correction."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import ssl
import urllib.error
import urllib.request
from ftplib import FTP_TLS
from pathlib import PurePosixPath

DEFAULT_ENDPOINT = "hollawall-language-switcher-20261120.php"
MARKER_START = "/* HollaWall language switcher UX START */"
MARKER_END = "/* HollaWall language switcher UX END */"

SWITCHER_CSS = f"""{MARKER_START}
/* Scope only the header desktop menu and mobile off-canvas menu. */
#menu-primary-menu li.menu-item-2054 a.ct-menu-link,
#menu-primary-menu-1 li.menu-item-2054 a.ct-menu-link {{
    display: inline-flex !important;
    align-items: center;
    justify-content: center;
    min-height: 44px;
    padding: 9px 13px !important;
    border: 1px solid currentColor;
    border-radius: 999px;
    line-height: 1;
    white-space: nowrap;
    transition: background-color .2s ease, color .2s ease, border-color .2s ease;
}}

#menu-primary-menu li.menu-item-2054 a.ct-menu-link:hover,
#menu-primary-menu li.menu-item-2054 a.ct-menu-link:focus-visible,
#menu-primary-menu-1 li.menu-item-2054 a.ct-menu-link:hover,
#menu-primary-menu-1 li.menu-item-2054 a.ct-menu-link:focus-visible {{
    background: #fb9202;
    color: #fff;
    border-color: #fb9202;
}}

#menu-primary-menu li.menu-item-2054 .trp-menu-ls-label,
#menu-primary-menu-1 li.menu-item-2054 .trp-menu-ls-label {{
    display: inline-flex;
    align-items: center;
    gap: 0;
    font-size: 0;
}}

#menu-primary-menu li.menu-item-2054 .trp-flag-image,
#menu-primary-menu-1 li.menu-item-2054 .trp-flag-image,
#menu-primary-menu li.menu-item-2054 .trp-ls-language-name,
#menu-primary-menu-1 li.menu-item-2054 .trp-ls-language-name {{
    display: none;
}}

/* The native TranslatePress anchor remains the target link. */
body.translatepress-id_ID #menu-primary-menu li.menu-item-2054 a::before,
body.translatepress-id_ID #menu-primary-menu-1 li.menu-item-2054 a::before {{
    content: "ID";
    font-size: 13px;
    font-weight: 800;
    letter-spacing: .04em;
}}
body.translatepress-id_ID #menu-primary-menu li.menu-item-2054 a::after,
body.translatepress-id_ID #menu-primary-menu-1 li.menu-item-2054 a::after {{
    content: " | EN";
    font-size: 13px;
    font-weight: 500;
    letter-spacing: .04em;
    opacity: .72;
}}
body.translatepress-en_US #menu-primary-menu li.menu-item-2054 a::before,
body.translatepress-en_US #menu-primary-menu-1 li.menu-item-2054 a::before {{
    content: "EN";
    font-size: 13px;
    font-weight: 800;
    letter-spacing: .04em;
}}
body.translatepress-en_US #menu-primary-menu li.menu-item-2054 a::after,
body.translatepress-en_US #menu-primary-menu-1 li.menu-item-2054 a::after {{
    content: " | ID";
    font-size: 13px;
    font-weight: 500;
    letter-spacing: .04em;
    opacity: .72;
}}

@media (max-width: 999px) {{
    #menu-primary-menu-1 li.menu-item-2054 a.ct-menu-link {{
        width: max-content;
        margin-top: 8px;
    }}
}}
{MARKER_END}"""


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable missing: {name}")
    return value


def safe_remote(path: str) -> str:
    parsed = PurePosixPath(path)
    if not path or parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ValueError(f"unsafe remote path: {path!r}")
    return parsed.as_posix()


def connect(host: str, user: str, password: str, port: int) -> FTP_TLS:
    ftp = FTP_TLS(context=ssl.create_default_context(), timeout=60)
    ftp.connect(host, port)
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def download(ftp: FTP_TLS, path: str) -> bytes:
    buffer = io.BytesIO()
    ftp.retrbinary(f"RETR {path}", buffer.write)
    return buffer.getvalue()


def exists(ftp: FTP_TLS, path: str) -> bool:
    try:
        ftp.size(path)
        return True
    except Exception:
        return False


def locate_wordpress_root(ftp: FTP_TLS) -> str:
    candidates = ("", "public_html", "hollawall.com/public_html", "domains/hollawall.com/public_html", "www")
    roots = [root for root in candidates if exists(ftp, f"{root + '/' if root else ''}wp-load.php")]
    if not roots:
        raise RuntimeError("WordPress document root not found")

    probe_name = f"hollawall-root-probe-{secrets.token_hex(12)}.txt"
    probe_body = secrets.token_urlsafe(32).encode("ascii")
    for root in roots:
        probe_remote = f"{root}/{probe_name}" if root else probe_name
        try:
            ftp.storbinary(f"STOR {probe_remote}", io.BytesIO(probe_body))
            ftp.sendcmd(f"SITE CHMOD 644 {probe_remote}")
            with urllib.request.urlopen(f"https://hollawall.com/{probe_name}", timeout=30) as response:
                if response.status == 200 and response.read() == probe_body:
                    return root
        except (OSError, urllib.error.URLError):
            pass
        finally:
            if exists(ftp, probe_remote):
                ftp.delete(probe_remote)
    raise RuntimeError("WordPress roots found, but none maps to the public site")


def php_single_quoted(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def build_runner(token: str) -> bytes:
    css = php_single_quoted(SWITCHER_CSS)
    php = f"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
$expected = {php_single_quoted(token)};
$received = isset($_SERVER['HTTP_X_HOLLAWALL_DEPLOY_TOKEN']) ? (string) $_SERVER['HTTP_X_HOLLAWALL_DEPLOY_TOKEN'] : '';
if (!hash_equals($expected, $received)) {{ http_response_code(403); echo json_encode(array('ok'=>false,'error'=>'forbidden')); exit; }}
$root = __DIR__;
if (file_exists($root . '/wp-load.php')) {{ require_once $root . '/wp-load.php'; }}
elseif (file_exists(dirname($root) . '/wp-load.php')) {{ require_once dirname($root) . '/wp-load.php'; }}
else {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'wp-load-not-found')); exit; }}

$post = wp_get_custom_css_post();
if (!$post) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'custom-css-post-missing')); exit; }}
$current = (string)$post->post_content;
$pattern = '~\\s*/\\* HollaWall language switcher UX START \\*/.*?/\\* HollaWall language switcher UX END \\*/\\s*~s';
$base = preg_replace($pattern, "\\n", $current);
if ($base === null) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'custom-css-cleanup-failed')); exit; }}
$css = {css};
$new_css = rtrim($base) . "\\n\\n" . $css . "\\n";
$updated = wp_update_post(array('ID'=>(int)$post->ID, 'post_content'=>$new_css), true);
if (is_wp_error($updated)) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$updated->get_error_message())); exit; }}
clean_post_cache((int)$post->ID);
if (function_exists('wp_cache_flush')) {{ wp_cache_flush(); }}
if (function_exists('wp_cache_clear_cache')) {{ wp_cache_clear_cache(); }}
if (function_exists('wpo_cache_flush')) {{ wpo_cache_flush(); }}
$readback = wp_get_custom_css_post();
$verified = $readback && strpos((string)$readback->post_content, 'HollaWall language switcher UX START') !== false && strpos((string)$readback->post_content, 'body.translatepress-en_US') !== false;
if (!$verified) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'custom-css-readback-failed')); exit; }}
echo json_encode(array('ok'=>true,'post_id'=>(int)$post->ID,'css_sha256'=>hash('sha256',(string)$readback->post_content),'marker_present'=>true));
"""
    return php.encode("utf-8")


def call_endpoint(url: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(url, method="POST", headers={"X-Hollawall-Deploy-Token": token, "User-Agent": "HollawallLanguageSwitcherDeploy/1"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"deploy endpoint HTTP {exc.code}: {payload[:1000]}") from exc
    if status != 200:
        raise RuntimeError(f"deploy endpoint HTTP {status}: {payload[:1000]}")
    result = json.loads(payload)
    if result.get("ok") is not True:
        raise RuntimeError(f"deploy endpoint failed: {result}")
    return result


def live_readback() -> dict[str, object]:
    checks: dict[str, object] = {}
    for path, expected_before, expected_after in (
        ("/projects/?hollawall-language-switcher=1", "ID", "| EN"),
        ("/en/projects/?hollawall-language-switcher=1", "EN", "| ID"),
    ):
        with urllib.request.urlopen("https://hollawall.com" + path, timeout=60) as response:
            html = response.read().decode("utf-8", errors="replace")
        result = {
            "http": response.status,
            "marker": MARKER_START in html,
            "css_id": expected_before in html,
            "css_target": expected_after in html,
        }
        checks[path] = result
        if not all((result["http"] == 200, result["marker"], result["css_id"], result["css_target"])):
            raise RuntimeError(f"live CSS readback failed for {path}: {result}")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=DEFAULT_ENDPOINT)
    parser.add_argument("--port", type=int, default=21)
    parser.add_argument("--evidence")
    args = parser.parse_args()

    host = require_env("RW_FTP_HOST")
    user = require_env("RW_FTP_USER")
    password = require_env("RW_FTP_PASSWORD")
    endpoint = safe_remote(args.remote)
    token = secrets.token_urlsafe(48)
    runner = build_runner(token)
    evidence: dict[str, object] = {
        "success": False,
        "runner_sha256": hashlib.sha256(runner).hexdigest(),
        "css_sha256": hashlib.sha256(SWITCHER_CSS.encode("utf-8")).hexdigest(),
        "runner_removed": False,
    }
    ftp = connect(host, user, password, args.port)
    remote = ""
    try:
        root = locate_wordpress_root(ftp)
        remote = f"{root}/{endpoint}" if root else endpoint
        evidence["remote"] = remote
        if exists(ftp, remote):
            raise RuntimeError(f"remote endpoint already exists: {remote}")
        ftp.storbinary(f"STOR {remote}", io.BytesIO(runner))
        ftp.sendcmd(f"SITE CHMOD 600 {remote}")
        if download(ftp, remote) != runner:
            raise RuntimeError("uploaded runner readback mismatch")
        result = call_endpoint("https://hollawall.com/" + endpoint, token)
        evidence.update(result)
        evidence["live_readback"] = live_readback()
        evidence["success"] = True
    finally:
        try:
            if remote and exists(ftp, remote):
                ftp.delete(remote)
            evidence["runner_removed"] = bool(remote) and not exists(ftp, remote)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    serialized = json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.evidence:
        with open(args.evidence, "w", encoding="utf-8") as handle:
            handle.write(serialized)
    print(serialized, end="")
    return 0 if evidence.get("success") is True and evidence.get("runner_removed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
