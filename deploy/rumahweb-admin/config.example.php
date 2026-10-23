<?php
declare(strict_types=1);

// Copy to /home/<hosting-user>/.hollawall-admin.php with mode 0600.
// Never place the live file inside public_html or Git.
return [
    'username' => 'CURRENT_DASHBOARD_USERNAME',
    'password_hash' => 'CURRENT_DASHBOARD_BCRYPT_HASH',
    'proxy_token' => 'OWNER_PROXY_TOKEN',
    'upstream_snapshot_url' => 'https://renewed-loreen-hollawalls-8d8f6f5c.koyeb.app/api/dashboard/v1/snapshot',
];