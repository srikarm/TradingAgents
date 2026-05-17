INSERT INTO users (id, github_id, email, created_at)
VALUES ('11111111-2222-3333-4444-555555555555', 'e2e-user', 'e2e-user@e2e.local', NOW())
ON CONFLICT (github_id) DO NOTHING;

INSERT INTO runs (id, user_id, ticker, trade_date, status, final_rating,
                  results_path, created_at, completed_at)
VALUES ('22222222-3333-4444-5555-666666666666',
        '11111111-2222-3333-4444-555555555555',
        'NVDA', '2024-05-10', 'succeeded', 'Buy',
        '/data/users/11111111-2222-3333-4444-555555555555/NVDA/2024-05-10',
        NOW(), NOW())
ON CONFLICT (id) DO NOTHING;
