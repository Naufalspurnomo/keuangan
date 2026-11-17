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
import time
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


def php_single_quoted(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def php_array(values: dict[str, str]) -> str:
    rows = [f"    {php_single_quoted(k)} => {php_single_quoted(v)}," for k, v in values.items()]
    return "array(\n" + "\n".join(rows) + "\n)"


def build_runner(token: str, source: dict[str, str], target: dict[str, str], slug: str) -> bytes:
    mapping = {
        source["title"]: target["title"],
        source["heading"]: target["heading"],
        source["body"]: target["body"],
        source["source_label"]: target["source_label"],
        source["source_value"]: target["source_value"],
    }
    content = (
        "<section class=\"hollawall-project-story\">"
        f"<h2>{source['heading']}</h2>"
        f"<p>{source['body']}</p>"
        f"<p><strong>{source['source_label']}</strong> {source['source_value']}</p>"
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
if ($existing) {{ http_response_code(409); echo json_encode(array('ok'=>false,'error'=>'slug-exists','post_id'=>(int)$existing->ID)); exit; }}

$content = {php_single_quoted(content)};
$post_id = wp_insert_post(array(
    'post_type' => 'project',
    'post_status' => 'publish',
    'post_title' => {php_single_quoted(source['title'])},
    'post_name' => $slug,
    'post_content' => $content,
    'post_excerpt' => {php_single_quoted(excerpt)},
    'post_author' => 1,
), true);
if (is_wp_error($post_id)) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$post_id->get_error_message())); exit; }}

$thumbnail_id = (int) attachment_url_to_postid('https://hollawall.com/wp-content/uploads/2026/09/Babak-1_Chapter-1.png');
if ($thumbnail_id > 0) {{ set_post_thumbnail($post_id, $thumbnail_id); }}

$translations = {php_array(mapping)};
$settings = get_option('trp_settings', array());
$default_language = !empty($settings['default-language']) ? (string)$settings['default-language'] : 'id_ID';
$target_language = 'en_US';
$languages = !empty($settings['translation-languages']) && is_array($settings['translation-languages']) ? $settings['translation-languages'] : array();
if (!in_array($target_language, $languages, true)) {{ wp_delete_post($post_id, true); http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translatepress-en-us-not-configured')); exit; }}

$table = $wpdb->prefix . 'trp_dictionary_' . strtolower(str_replace('-', '_', $default_language)) . '_' . strtolower(str_replace('-', '_', $target_language));
$table_like = $wpdb->esc_like($table);
$table_exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table_like));
if ($table_exists !== $table) {{ wp_delete_post($post_id, true); http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translatepress-table-missing')); exit; }}

$created_ids = array();
foreach ($translations as $original => $translated) {{
    $row = $wpdb->get_row($wpdb->prepare("SELECT id, translated, status, block_type FROM `$table` WHERE BINARY original = %s ORDER BY id ASC LIMIT 1", $original), ARRAY_A);
    if ($row) {{
        if ((string)$row['translated'] !== (string)$translated || (int)$row['status'] !== 2) {{
            wp_delete_post($post_id, true);
            http_response_code(409);
            echo json_encode(array('ok'=>false,'error'=>'translation-conflict','original'=>$original));
            exit;
        }}
        continue;
    }}
    $ok = $wpdb->insert($table, array('original'=>$original,'translated'=>$translated,'status'=>2,'block_type'=>0), array('%s','%s','%d','%d'));
    if ($ok === false) {{
        foreach ($created_ids as $created_id) {{ $wpdb->delete($table, array('id'=>$created_id), array('%d')); }}
        wp_delete_post($post_id, true);
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
    wp_delete_post($post_id, true);
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
    remote = safe_remote(args.remote)
    if args.slug != DEFAULT_SLUG:
        raise RuntimeError("unexpected slug")

    source = {
        "title": "History of Jl. Tunjungan",
        "heading": "Sejarah Jl. Tunjungan",
        "body": "Sejak tahun 1888, Jalan Tunjungan berkembang menjadi salah satu kawasan perdagangan dan perbelanjaan utama di Surabaya. Pertumbuhannya didukung oleh jaringan trem yang menghubungkan kawasan ini dengan Krian, Wonokromo, dan Jembatan Merah. Deretan toko, pusat perbelanjaan, dan hotel menjadikan Tunjungan sebagai jalan perbelanjaan terkemuka yang mencerminkan geliat ekonomi dan perkembangan perkotaan Surabaya pada masa kolonial. Setelah mengalami penurunan aktivitas perdagangan pada dekade 1990-an, Jalan Tunjungan dihidupkan kembali melalui revitalisasi kota. Kini, kawasan ini menjadi destinasi wisata warisan budaya dan ruang publik yang semarak, dengan beragam kuliner, kafe, serta kegiatan seni dan budaya. Bangunan bersejarah seperti Siola dan deretan rumah toko lama menjadi bagian penting dari identitas kawasan ini.",
        "source_label": "Sumber:",
        "source_value": "#CeritaMuralTunjungan",
    }
    target = {
        "title": "History of Jl. Tunjungan",
        "heading": "History of Jl. Tunjungan",
        "body": "Since 1888, Jalan Tunjungan has developed into one of Surabaya’s major commercial and shopping districts. Its growth was supported by a tram network connecting the area with Krian, Wonokromo, and Jembatan Merah. Rows of shops, shopping establishments, and hotels transformed Tunjungan into a prominent shopping street, reflecting Surabaya’s economic vitality and urban development during the colonial era. After experiencing a decline in commercial activity during the 1990s, Jalan Tunjungan was brought back to life through urban revitalization. Today, it is a heritage tourism destination and a vibrant public space featuring culinary attractions, cafés, and various arts and cultural activities. Historic buildings such as Siola, along with the district’s old shophouses, form an important part of the area’s identity.",
        "source_label": "Source:",
        "source_value": "#CeritaMuralTunjungan",
    }

    token = secrets.token_urlsafe(48)
    runner = build_runner(token, source, target, args.slug)
    evidence: dict[str, object] = {
        "success": False,
        "remote": remote,
        "slug": args.slug,
        "runner_sha256": hashlib.sha256(runner).hexdigest(),
        "runner_removed": False,
    }
    ftp = connect(host, user, password, args.port)
    try:
        if exists(ftp, remote):
            raise RuntimeError(f"remote endpoint already exists: {remote}")
        ftp.storbinary(f"STOR {remote}", io.BytesIO(runner))
        ftp.sendcmd(f"SITE CHMOD 600 {remote}")
        if download(ftp, remote) != runner:
            raise RuntimeError("uploaded runner readback mismatch")
        endpoint_url = "https://hollawall.com/" + remote
        result = call_endpoint(endpoint_url, token)
        evidence.update(result)
        evidence["success"] = True
    finally:
        try:
            if exists(ftp, remote):
                ftp.delete(remote)
            evidence["runner_removed"] = not exists(ftp, remote)
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
