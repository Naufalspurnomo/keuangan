<?php
/**
 * Copy to /home/<hosting-user>/.hollawall-presensi.php, verify the active
 * project list against the dashboard source of truth, then chmod 0600.
 * GPS coordinates are captured per Check-in/Check-out, not configured here.
 */
return [
    'retention_days' => 90,
    'employees' => [
        ['id' => 'pegawai-1', 'name' => 'Pegawai 1'],
        ['id' => 'pegawai-2', 'name' => 'Pegawai 2'],
        ['id' => 'pegawai-3', 'name' => 'Pegawai 3'],
    ],
    'projects' => [
        ['id' => 'p25-umbara', 'name' => 'Umbara Headquarters', 'company' => 'Holla', 'active' => true],
        ['id' => 'p25-vistara', 'name' => 'Vistara Convention', 'company' => 'Hojja', 'active' => true],
        ['id' => 'p25-xanadu', 'name' => 'Xanadu Experience Center', 'company' => 'Texturin Surabaya', 'active' => true],
        ['id' => 'p26-dahayu', 'name' => 'Dahayu Boutique Hotel', 'company' => 'Hojja', 'active' => true],
        ['id' => 'p26-elok', 'name' => 'Elok Seaside Restaurant', 'company' => 'Texturin Bali', 'active' => true],
        ['id' => 'p26-fajar', 'name' => 'Fajar Distribution Hub', 'company' => 'Texturin Surabaya', 'active' => true],
        ['id' => 'p26-griya', 'name' => 'Griya Wellness Center', 'company' => 'Holla', 'active' => true],
        ['id' => 'p26-harmoni', 'name' => 'Harmoni Kids Library', 'company' => 'Hojja', 'active' => true],
    ],
];
