#!/usr/bin/env python3
"""One-shot FTPS deployment for the bilingual History of Jl. Tunjungan project article.

The script is intentionally bounded: it creates one WordPress `project` post plus
its manual TranslatePress dictionary entries, captures sanitized evidence, and
removes the temporary server-side runner after verified readback. It never
prints the FTP password or database credentials.
"""
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

DEFAULT_ENDPOINT = "hollawall-content-deploy-20261117.php"
DEFAULT_SLUG = "history-of-jl-tunjungan"


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


def ensure_directory(ftp: FTP_TLS, path: str) -> None:
    current = ftp.pwd()
    try:
        ftp.cwd(path)
        return
    except Exception:
        try:
            ftp.mkd(path)
            ftp.cwd(path)
        except Exception as exc:
            raise RuntimeError(f"unable to create remote directory: {path}") from exc
    finally:
        ftp.cwd(current)


def locate_wordpress_root(ftp: FTP_TLS) -> str:
    candidates = (
        "",
        "public_html",
        "hollawall.com/public_html",
        "domains/hollawall.com/public_html",
        "www",
    )
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


def php_array(values: dict[str, str]) -> str:
    rows = [f"    {php_single_quoted(k)} => {php_single_quoted(v)}," for k, v in values.items()]
    return "array(\n" + "\n".join(rows) + "\n)"


def build_runner(token: str, source: dict[str, str], target: dict[str, str], slug: str, image_name: str) -> bytes:
    mapping = {
        source["title"]: target["title"],
        source["heading"]: target["heading"],
        source["body"]: target["body"],
        source["source_line"]: target["source_line"],
        source["cover_alt"]: target["cover_alt"],
    }
    image_url = f"https://hollawall.com/wp-content/uploads/hollawall-projects/{image_name}"
    content = (
        "<section class=\"hollawall-project-story\">"
        "<figure class=\"wp-block-image size-full\">"
        f"<img src=\"{image_url}\" alt=\"{source['cover_alt']}\" width=\"1159\" height=\"846\" />"
        "</figure>"
        f"<h2>{source['heading']}</h2>"
        f"<p>{source['body']}</p>"
        f"<p>{source['source_line']}</p>"
        "</section>"
    )
    excerpt = source["body"]
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

$slug = {php_single_quoted(slug)};
$existing = get_page_by_path($slug, OBJECT, 'project');
$content = {php_single_quoted(content)};
$post_payload = array(
    'post_type' => 'project',
    'post_status' => 'publish',
    'post_title' => {php_single_quoted(source['title'])},
    'post_name' => $slug,
    'post_content' => $content,
    'post_excerpt' => {php_single_quoted(excerpt)},
    'post_author' => 1,
);
if ($existing) {{
    $post_payload['ID'] = (int)$existing->ID;
    $post_id = wp_update_post($post_payload, true);
}} else {{
    $post_id = wp_insert_post($post_payload, true);
}}
if (is_wp_error($post_id)) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$post_id->get_error_message())); exit; }}

$upload = wp_upload_dir();
$image_path = $upload['basedir'] . '/hollawall-projects/' . {php_single_quoted(image_name)};
$image_url = $upload['baseurl'] . '/hollawall-projects/' . {php_single_quoted(image_name)};
if (!file_exists($image_path)) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'uploaded-image-missing')); exit; }}
$thumbnail_id = (int) attachment_url_to_postid($image_url);
if ($thumbnail_id === 0) {{
    $filetype = wp_check_filetype(basename($image_path), null);
    $thumbnail_id = wp_insert_attachment(array(
        'post_mime_type' => $filetype['type'],
        'post_title' => {php_single_quoted(source['title'])},
        'post_content' => '',
        'post_status' => 'inherit',
    ), $image_path, $post_id, true);
    if (is_wp_error($thumbnail_id)) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$thumbnail_id->get_error_message())); exit; }}
    require_once ABSPATH . 'wp-admin/includes/image.php';
    $metadata = wp_generate_attachment_metadata($thumbnail_id, $image_path);
    wp_update_attachment_metadata($thumbnail_id, $metadata);
}}
update_post_meta($thumbnail_id, '_wp_attachment_image_alt', {php_single_quoted(source['cover_alt'])});
set_post_thumbnail($post_id, $thumbnail_id);

$translations = {php_array(mapping)};
$settings = get_option('trp_settings', array());
$default_language = !empty($settings['default-language']) ? (string)$settings['default-language'] : 'id_ID';
$target_language = 'en_US';
$languages = !empty($settings['translation-languages']) && is_array($settings['translation-languages']) ? $settings['translation-languages'] : array();
if (!in_array($target_language, $languages, true)) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translatepress-en-us-not-configured')); exit; }}

$table = $wpdb->prefix . 'trp_dictionary_' . strtolower(str_replace('-', '_', $default_language)) . '_' . strtolower(str_replace('-', '_', $target_language));
$table_like = $wpdb->esc_like($table);
$table_exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table_like));
if ($table_exists !== $table) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translatepress-table-missing')); exit; }}

$created_ids = array();
foreach ($translations as $original => $translated) {{
    $row = $wpdb->get_row($wpdb->prepare("SELECT id, translated, status, block_type FROM `$table` WHERE BINARY original = %s ORDER BY id ASC LIMIT 1", $original), ARRAY_A);
    if ($row) {{
        if ((string)$row['translated'] !== (string)$translated || (int)$row['status'] !== 2) {{
            if (!$existing) {{ wp_delete_post($post_id, true); }}
            http_response_code(409);
            echo json_encode(array('ok'=>false,'error'=>'translation-conflict','original'=>$original));
            exit;
        }}
        continue;
    }}
    $ok = $wpdb->insert($table, array('original'=>$original,'translated'=>$translated,'status'=>2,'block_type'=>0), array('%s','%s','%d','%d'));
    if ($ok === false) {{
        foreach ($created_ids as $created_id) {{ $wpdb->delete($table, array('id'=>$created_id), array('%d')); }}
        if (!$existing) {{ wp_delete_post($post_id, true); }}
        http_response_code(500);
        echo json_encode(array('ok'=>false,'error'=>'translation-insert-failed'));
        exit;
    }}
    $created_ids[] = (int)$wpdb->insert_id;
}}

clean_post_cache($post_id);
if (function_exists('wp_cache_flush')) {{ wp_cache_flush(); }}
$readback = get_post($post_id);
$verified = $readback && $readback->post_status === 'publish' && $readback->post_name === $slug && $readback->post_title === {php_single_quoted(source['title'])} && strpos($readback->post_content, {php_single_quoted(source['body'])}) !== false;
if (!$verified) {{
    foreach ($created_ids as $created_id) {{ $wpdb->delete($table, array('id'=>$created_id), array('%d')); }}
    if (!$existing) {{ wp_delete_post($post_id, true); }}
    http_response_code(500);
    echo json_encode(array('ok'=>false,'error'=>'post-readback-failed'));
    exit;
}}

echo json_encode(array(
    'ok'=>true,
    'post_id'=>(int)$post_id,
    'slug'=>$slug,
    'status'=>$readback->post_status,
    'permalink'=>get_permalink($post_id),
    'english_permalink'=>trailingslashit(home_url('/en/project/' . $slug)),
    'featured_media'=>$thumbnail_id,
    'translation_count'=>count($translations),
    'new_translation_rows'=>count($created_ids),
    'default_language'=>$default_language,
    'target_language'=>$target_language,
), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
"""
    return php.encode("utf-8")


def call_endpoint(url: str, token: str) -> dict[str, object]:
    req = urllib.request.Request(url, method="POST", headers={"X-Hollawall-Deploy-Token": token, "User-Agent": "HollawallContentDeploy/1"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=DEFAULT_ENDPOINT)
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument("--port", type=int, default=21)
    parser.add_argument("--evidence")
    args = parser.parse_args()

    host = require_env("RW_FTP_HOST")
    user = require_env("RW_FTP_USER")
    password = require_env("RW_FTP_PASSWORD")
    endpoint = safe_remote(args.remote)
    if args.slug != DEFAULT_SLUG:
        raise RuntimeError("unexpected slug")

    source = {
        "title": "Sejarah Jl. Tunjungan",
        "heading": "SEJARAH JL. TUNJUNGAN",
        "body": "Sejak 1888, Jalan Tunjungan berkembang menjadi salah satu pusat perdagangan dan perbelanjaan penting di Surabaya. Perkembangannya didukung oleh jaringan trem yang menghubungkan kawasan ini dengan Krian, Wonokromo, hingga Jembatan Merah. Deretan pertokoan, pusat perbelanjaan, dan hotel menjadikan Tunjungan sebagai shopping street yang mencerminkan dinamika kehidupan ekonomi dan perkotaan Surabaya pada masa kolonial. Setelah mengalami kemunduran aktivitas pada dekade 1990-an, Jalan Tunjungan kembali hidup melalui revitalisasi kawasan. Kini, kawasan ini menjadi destinasi wisata heritage sekaligus ruang publik yang menawarkan kuliner, kafe, serta kegiatan seni dan budaya. Bangunan bersejarah seperti Siola dan berbagai bangunan pertokoan lama menjadi bagian dari identitas Tunjungan sebagai salah satu ikon sejarah dan gaya hidup Kota Surabaya.",
        "source_line": "Sumber: #CeritaMuralTunjungan",
        "cover_alt": "Ilustrasi sejarah Jalan Tunjungan dengan trem, kereta kuda, dan bangunan bersejarah Surabaya",
    }
    target = {
        "title": "History of Jl. Tunjungan",
        "heading": "HISTORY OF JL. TUNJUNGAN",
        "body": "Since 1888, Jalan Tunjungan has developed into one of Surabaya’s major commercial and shopping districts. Its growth was supported by a tram network connecting the area with Krian, Wonokromo, and Jembatan Merah. Rows of shops, shopping establishments, and hotels transformed Tunjungan into a prominent shopping street, reflecting Surabaya’s economic vitality and urban development during the colonial era. After experiencing a decline in commercial activity during the 1990s, Jalan Tunjungan was brought back to life through urban revitalization. Today, it is a heritage tourism destination and a vibrant public space featuring culinary attractions, cafés, and various arts and cultural activities. Historic buildings such as Siola, along with the district’s old shophouses, form an important part of Tunjungan’s identity as one of Surabaya’s icons of history and urban lifestyle.",
        "source_line": "Source: #CeritaMuralTunjungan",
        "cover_alt": "Historical illustration of Jalan Tunjungan featuring a tram, horse-drawn carriages, and Surabaya heritage buildings",
    }

    image_name = "history-jl-tunjungan.jpg"
    image_bytes = open(image_name, "rb").read()
    token = secrets.token_urlsafe(48)
    runner = build_runner(token, source, target, args.slug, image_name)
    evidence: dict[str, object] = {
        "success": False,
        "slug": args.slug,
        "runner_sha256": hashlib.sha256(runner).hexdigest(),
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "runner_removed": False,
    }
    ftp = connect(host, user, password, args.port)
    remote = ""
    try:
        root = locate_wordpress_root(ftp)
        remote = f"{root}/{endpoint}" if root else endpoint
        image_directory = f"{root}/wp-content/uploads/hollawall-projects" if root else "wp-content/uploads/hollawall-projects"
        image_remote = f"{image_directory}/{image_name}"
        evidence["wordpress_root_detected"] = True
        evidence["remote"] = remote
        evidence["image_remote"] = image_remote
        if exists(ftp, remote):
            raise RuntimeError(f"remote endpoint already exists: {remote}")
        ensure_directory(ftp, image_directory)
        if exists(ftp, image_remote):
            if download(ftp, image_remote) != image_bytes:
                raise RuntimeError("remote image exists with different bytes")
        else:
            ftp.storbinary(f"STOR {image_remote}", io.BytesIO(image_bytes))
            ftp.sendcmd(f"SITE CHMOD 644 {image_remote}")
            if download(ftp, image_remote) != image_bytes:
                raise RuntimeError("uploaded image readback mismatch")
        ftp.storbinary(f"STOR {remote}", io.BytesIO(runner))
        ftp.sendcmd(f"SITE CHMOD 600 {remote}")
        if download(ftp, remote) != runner:
            raise RuntimeError("uploaded runner readback mismatch")
        result = call_endpoint("https://hollawall.com/" + endpoint, token)
        evidence.update(result)
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
    if evidence.get("success") is not True or evidence.get("runner_removed") is not True:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
