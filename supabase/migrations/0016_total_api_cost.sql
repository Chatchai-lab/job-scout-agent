-- All-time spend on the API, for the remaining-credit display in the app.
create view total_api_cost as
select coalesce(sum(cost_usd), 0) as cost_usd from llm_usage;
