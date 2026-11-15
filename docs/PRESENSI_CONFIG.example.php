<?php
/**
 * Copy to /home/<hosting-user>/.hollawall-presensi.php and chmod 0600.
 * Generate each PIN hash with:
 *   php -r "echo password_hash('REPLACE-PIN', PASSWORD_DEFAULT), PHP_EOL;"
 * Generate the outbox secret with:
 *   php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"
 * Never place plaintext PINs or the outbox secret in the web root or repository.
 */
return [
    'retention_days' => 90,
    'outbox_shared_secret' => 'replace-with-a-random-64-character-hex-secret-before-deploying',
    'delivery_trigger_url' => 'https://your-backend.example/internal/presensi/deliver',
    'project_catalog_url' => 'https://your-backend.example/internal/presensi/projects',
    'employees' => [
        [
            'id' => 'pegawai-1',
            'name' => 'Pegawai 1',
            'code' => 'EMP001',
            'pin_hash' => '$2y$10$7OuurItIj7ylUssqZ9D7MuqfBJGMN6U9.2sRCO1obS0ys04e..J.G',
        ],
        [
            'id' => 'pegawai-2',
            'name' => 'Pegawai 2',
            'code' => 'EMP002',
            'pin_hash' => '$2y$10$7OuurItIj7ylUssqZ9D7MuqfBJGMN6U9.2sRCO1obS0ys04e..J.G',
        ],
        [
            'id' => 'pegawai-3',
            'name' => 'Pegawai 3',
            'code' => 'EMP003',
            'pin_hash' => '$2y$10$7OuurItIj7ylUssqZ9D7MuqfBJGMN6U9.2sRCO1obS0ys04e..J.G',
        ],
    ],
];
