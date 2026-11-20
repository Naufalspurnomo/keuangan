<?php
declare(strict_types=1);

function canonical_finance_proxy_ready(array $config): bool
{
    if (($config['canonical_finance_writes_enabled'] ?? false) !== true) {
        return false;
    }

    $url = trim((string) ($config['upstream_canonical_transactions_url'] ?? ''));
    $parts = parse_url($url);
    if (!is_array($parts)
        || strtolower((string) ($parts['scheme'] ?? '')) !== 'https'
        || (string) ($parts['host'] ?? '') === ''
        || rtrim((string) ($parts['path'] ?? ''), '/') !== '/api/dashboard/v1/canonical-transactions'
        || isset($parts['user'])
        || isset($parts['pass'])
        || isset($parts['query'])
        || isset($parts['fragment'])) {
        return false;
    }

    $secret = (string) ($config['dashboard_actor_assertion_secret'] ?? '');
    $audience = trim((string) ($config['dashboard_actor_assertion_audience'] ?? ''));
    $email = trim((string) ($config['owner_email'] ?? ''));
    $token = (string) ($config['proxy_token'] ?? '');

    return strlen($secret) >= 32
        && $audience !== ''
        && $email !== ''
        && preg_match('/^[^\x00-\x1F\x7F]{16,512}$/D', $token) === 1;
}
