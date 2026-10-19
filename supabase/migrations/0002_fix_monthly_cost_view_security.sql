-- The view ran as SECURITY DEFINER (Postgres default), which would let a
-- caller read it under the view owner's privileges and bypass RLS on
-- llm_usage. Switch it to SECURITY INVOKER so it respects the querying
-- role's own row-level security.
alter view monthly_cost set (security_invoker = true);
