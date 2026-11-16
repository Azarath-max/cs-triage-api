-- Demo data for local runs and for trying the API end to end.
-- Loaded automatically by docker compose. Not for production.

INSERT INTO customers (
    company_name, contact_name, contact_email, plan,
    adoption_score, health_status, health_declining, days_to_renewal
) VALUES
    -- Healthy, far from renewal: high-confidence messages can auto-send.
    ('Northwind Logistics', 'Ada Lovelace', 'ada@example.com', 'growth', 82, 'healthy', false, 240),
    -- Low adoption and near renewal: the rules should escalate this to at_risk.
    ('Contoso Health', 'Grace Hopper', 'grace@example.com', 'enterprise', 34, 'watch', true, 60),
    -- Already at risk in the database: rules may raise it but must not lower it.
    ('Fabrikam Retail', 'Alan Turing', 'alan@example.com', 'standard', 61, 'at_risk', true, 45)
ON CONFLICT (contact_email) DO NOTHING;
