#!/usr/bin/env python3
"""One-shot FTPS deployment for the bilingual Gombloh project article."""
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

DEFAULT_ENDPOINT = "hollawall-gombloh-deploy-20261118.php"
DEFAULT_SLUG = "gombloh-sang-musisi-legendaris"


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


def php_array(values: dict[str, str]) -> str:
    rows = [f"    {php_single_quoted(k)} => {php_single_quoted(v)}," for k, v in values.items()]
    return "array(\n" + "\n".join(rows) + "\n)"


def build_runner(token: str, source: dict[str, str], target: dict[str, str], slug: str, image_name: str) -> bytes:
    mapping = {
        source["title"]: target["title"],
        source["heading"]: target["heading"],
        source["p1"]: target["p1"],
        source["p2"]: target["p2"],
        source["p3"]: target["p3"],
        source["source_line"]: target["source_line"],
        source["cover_alt"]: target["cover_alt"],
    }
    image_url = f"https://hollawall.com/wp-content/uploads/hollawall-projects/{image_name}"
    content = (
        "<figure class=\"wp-block-image size-full hollawall-project-artwork\">"
        f"<img src=\"{image_url}\" alt=\"{source['cover_alt']}\" width=\"1135\" height=\"928\" />"
        "</figure>"
        "<section class=\"hollawall-project-story\">"
        f"<h2>{source['heading']}</h2>"
        f"<p>{source['p1']}</p>"
        f"<p>{source['p2']}</p>"
        f"<p>{source['p3']}</p>"
        f"<p>{source['source_line']}</p>"
        "</section>"
    )
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
    'post_type' => 'project', 'post_status' => 'publish',
    'post_title' => {php_single_quoted(source['title'])}, 'post_name' => $slug,
    'post_content' => $content, 'post_excerpt' => {php_single_quoted(source['excerpt'])}, 'post_author' => 1,
);
if ($existing) {{ $post_payload['ID'] = (int)$existing->ID; $post_id = wp_update_post($post_payload, true); }}
else {{ $post_id = wp_insert_post($post_payload, true); }}
if (is_wp_error($post_id)) {{ http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$post_id->get_error_message())); exit; }}
$upload = wp_upload_dir();
$image_path = $upload['basedir'] . '/hollawall-projects/' . {php_single_quoted(image_name)};
$image_url = $upload['baseurl'] . '/hollawall-projects/' . {php_single_quoted(image_name)};
if (!file_exists($image_path)) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'uploaded-image-missing')); exit; }}
$thumbnail_id = (int) attachment_url_to_postid($image_url);
if ($thumbnail_id === 0) {{
    $filetype = wp_check_filetype(basename($image_path), null);
    $thumbnail_id = wp_insert_attachment(array('post_mime_type'=>$filetype['type'],'post_title'=>{php_single_quoted(source['title'])},'post_content'=>'','post_status'=>'inherit'), $image_path, $post_id, true);
    if (is_wp_error($thumbnail_id)) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>$thumbnail_id->get_error_message())); exit; }}
    require_once ABSPATH . 'wp-admin/includes/image.php';
    wp_update_attachment_metadata($thumbnail_id, wp_generate_attachment_metadata($thumbnail_id, $image_path));
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
$table_exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $wpdb->esc_like($table)));
if ($table_exists !== $table) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translatepress-table-missing')); exit; }}
$created_ids = array();
foreach ($translations as $original => $translated) {{
    $row = $wpdb->get_row($wpdb->prepare("SELECT id, translated, status FROM `$table` WHERE BINARY original = %s ORDER BY id ASC LIMIT 1", $original), ARRAY_A);
    if ($row) {{
        if ((string)$row['translated'] !== (string)$translated || (int)$row['status'] !== 2) {{ if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(409); echo json_encode(array('ok'=>false,'error'=>'translation-conflict','original'=>$original)); exit; }}
        continue;
    }}
    $ok = $wpdb->insert($table, array('original'=>$original,'translated'=>$translated,'status'=>2,'block_type'=>0), array('%s','%s','%d','%d'));
    if ($ok === false) {{ foreach ($created_ids as $created_id) {{ $wpdb->delete($table, array('id'=>$created_id), array('%d')); }} if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'translation-insert-failed')); exit; }}
    $created_ids[] = (int)$wpdb->insert_id;
}}
clean_post_cache($post_id);
if (function_exists('wp_cache_flush')) {{ wp_cache_flush(); }}
if (function_exists('wp_cache_clear_cache')) {{ wp_cache_clear_cache(); }}
if (function_exists('wpo_cache_flush')) {{ wpo_cache_flush(); }}
if (defined('WPO_CACHE_DIR') && is_dir(WPO_CACHE_DIR)) {{
    $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator(WPO_CACHE_DIR, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($iterator as $item) {{ if ($item->isDir()) {{ @rmdir($item->getPathname()); }} else {{ @unlink($item->getPathname()); }} }}
}}
$readback = get_post($post_id);
$verified = $readback && $readback->post_status === 'publish' && $readback->post_name === $slug && $readback->post_title === {php_single_quoted(source['title'])} && strpos($readback->post_content, {php_single_quoted(source['p1'])}) !== false;
if (!$verified) {{ foreach ($created_ids as $created_id) {{ $wpdb->delete($table, array('id'=>$created_id), array('%d')); }} if (!$existing) {{ wp_delete_post($post_id, true); }} http_response_code(500); echo json_encode(array('ok'=>false,'error'=>'post-readback-failed')); exit; }}
echo json_encode(array('ok'=>true,'post_id'=>(int)$post_id,'slug'=>$slug,'status'=>$readback->post_status,'permalink'=>get_permalink($post_id),'english_permalink'=>trailingslashit(home_url('/en/project/' . $slug)),'featured_media'=>$thumbnail_id,'translation_count'=>count($translations),'new_translation_rows'=>count($created_ids),'default_language'=>$default_language,'target_language'=>$target_language), JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
"""
    return php.encode("utf-8")


def call_endpoint(url: str, token: str) -> dict[str, object]:
    req = urllib.request.Request(url, method="POST", headers={"X-Hollawall-Deploy-Token": token, "User-Agent": "HollawallContentDeploy/1"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload, status = response.read().decode("utf-8"), response.status
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
    host, user, password = require_env("RW_FTP_HOST"), require_env("RW_FTP_USER"), require_env("RW_FTP_PASSWORD")
    endpoint = safe_remote(args.remote)
    if args.slug != DEFAULT_SLUG:
        raise RuntimeError("unexpected slug")
    source = {
        "title": "GOMBLOH: SANG MUSISI LEGENDARIS",
        "heading": "GOMBLOH: SANG MUSISI LEGENDARIS",
        "p1": "Soedjarwoto Soemarsono, yang dikenal dengan nama Gombloh, merupakan musisi dan pencipta lagu legendaris Indonesia. Orang tua Gombloh merupakan warga asli Surabaya, mereka bertempat tinggal di Lawang Seketeng Gang IV. Namun, tahun 1948 terjadi Agresi Militer Belanda II, sehingga mereka harus mengungsi di Jombang, Jawa Timur. Di sanalah Gombloh lahir, tepatnya di Tawangsari, Jombang pada 12 Juli 1948. Meskipun lahir di Jombang, Gombloh tumbuh dan berkarya di Surabaya. Selain dikenal sebagai seniman, Gombloh juga pernah menempuh pendidikan arsitektur di Institut Teknologi Sepuluh Nopember (ITS) Surabaya sebelum memilih untuk lebih mendalami dunia musik.",
        "p2": "Perjalanan musiknya berkembang sejak akhir 1960-an. Pada 1969, Gombloh bersama Leo Kristi dan sejumlah musisi lainnya membentuk grup musik yang bernama Lemon Tree’s Anno ’69 yang mengusung aliran folk. Melalui musik, ia mengangkat beragam kisah kehidupan masyarakat, kritik sosial, dan persoalan kemanusiaan dengan gaya yang khas dan dekat dengan kehidupan sehari-hari. Salah satu karyanya yang paling dikenal adalah Kebyar-Kebyar, lagu yang menggambarkan kecintaan terhadap Indonesia dan semangat persatuan. Kepeduliannya terhadap lingkungan juga tercermin dalam lagu Berita Cuaca.",
        "p3": "Gombloh meninggal dunia di Surabaya pada 9 Januari 1988, dalam usia 39 tahun. Meski perjalanan hidupnya terbilang singkat, karya-karyanya terus dikenang dan diwariskan lintas generasi.",
        "source_line": "Sumber: Buku Gombloh: Revolusi Cinta dari Surabaya karya Guruh Dimas Nugraha & Moegers (Kelompok Penggemar Gombloh) · #CeritaMuralTunjungan",
        "excerpt": "Pemkot Surabaya X Hollawall",
        "cover_alt": "Ilustrasi Gombloh bermain gitar dengan latar panggung musik dan bangunan bersejarah Tunjungan",
    }
    target = {
        "title": "GOMBLOH: THE LEGENDARY MUSICIAN",
        "heading": "GOMBLOH: THE LEGENDARY MUSICIAN",
        "p1": "Soedjarwoto Soemarsono, known as Gombloh, was a legendary Indonesian musician and songwriter. Gombloh’s parents were natives of Surabaya; they lived on Lawang Seketeng Gang IV. However, in 1948, the Second Dutch Military Aggression occurred, forcing them to flee to Jombang, East Java. It was there that Gombloh was born, specifically in Tawangsari, Jombang, on July 12, 1948. Although he was born in Jombang, Gombloh grew up and pursued his career in Surabaya. In addition to being known as an artist, Gombloh also studied architecture at the Sepuluh Nopember Institute of Technology (ITS) in Surabaya before choosing to delve deeper into the world of music.",
        "p2": "His musical journey began in the late 1960s. In 1969, Gombloh, along with Leo Kristi and several other musicians, formed the folk band Lemon Tree’s Anno ’69. Through his music, he highlighted a variety of stories about people’s lives, social criticism, and humanitarian issues in a distinctive style that resonated with everyday life. One of his best-known works is Kebyar-Kebyar, a song that expresses love for Indonesia and a spirit of unity. His concern for the environment is also reflected in the song Berita Cuaca.",
        "p3": "Gombloh passed away in Surabaya on January 9, 1988, at the age of 39. Although his life was relatively short, his works continue to be remembered and passed down across generations.",
        "source_line": "Source: Gombloh: The Love Revolution from Surabaya by Guruh Dimas Nugraha & Moegers (Gombloh Fan Club) · #CeritaMuralTunjungan",
        "excerpt": "Pemkot Surabaya X Hollawall",
        "cover_alt": "Illustration of Gombloh playing guitar against a musical stage and a historic Tunjungan building",
    }
    image_name = "gombloh.jpg"
    image_bytes = open(image_name, "rb").read()
    token = secrets.token_urlsafe(48)
    runner = build_runner(token, source, target, args.slug, image_name)
    evidence: dict[str, object] = {"success": False, "slug": args.slug, "runner_sha256": hashlib.sha256(runner).hexdigest(), "image_sha256": hashlib.sha256(image_bytes).hexdigest(), "runner_removed": False}
    ftp = connect(host, user, password, args.port)
    remote = ""
    try:
        root = locate_wordpress_root(ftp)
        remote = f"{root}/{endpoint}" if root else endpoint
        image_directory = f"{root}/wp-content/uploads/hollawall-projects" if root else "wp-content/uploads/hollawall-projects"
        image_remote = f"{image_directory}/{image_name}"
        evidence.update({"wordpress_root_detected": True, "remote": remote, "image_remote": image_remote})
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
        evidence.update(call_endpoint("https://hollawall.com/" + endpoint, token))
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
