<?php
/**
 * Copy to /home/<hosting-user>/.hollawall-presensi.php, replace every
 * null coordinate with an owner-verified project pin, then chmod 0600.
 * This example intentionally fails closed until all required values are set.
 */
return [
    'retention_days' => 90,
    'employees' => [
        ['id' => 'pegawai-1', 'name' => 'Pegawai 1'],
        ['id' => 'pegawai-2', 'name' => 'Pegawai 2'],
        ['id' => 'pegawai-3', 'name' => 'Pegawai 3'],
    ],
    'projects' => [
        ['id' => 'p25-umbara', 'name' => 'Umbara Headquarters', 'company' => 'Holla', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p25-vistara', 'name' => 'Vistara Convention', 'company' => 'Hojja', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p25-xanadu', 'name' => 'Xanadu Experience Center', 'company' => 'Texturin Surabaya', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p26-dahayu', 'name' => 'Dahayu Boutique Hotel', 'company' => 'Hojja', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p26-elok', 'name' => 'Elok Seaside Restaurant', 'company' => 'Texturin Bali', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p26-fajar', 'name' => 'Fajar Distribution Hub', 'company' => 'Texturin Surabaya', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p26-griya', 'name' => 'Griya Wellness Center', 'company' => 'Holla', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
        ['id' => 'p26-harmoni', 'name' => 'Harmoni Kids Library', 'company' => 'Hojja', 'location_label' => 'VERIFIED_LABEL_REQUIRED', 'latitude' => null, 'longitude' => null, 'radius_m' => 150, 'max_accuracy_m' => 50, 'active' => true],
    ],
];
