-- 26/11/2026 · Quant Office · cole no Supabase: SQL Editor -> New query -> Run. Pode rodar mais de uma vez.
--
-- 1) Histórico do saldo para o gráfico da parede (escrito só pelo sync, com a chave secreta).
-- 2) SEGURANÇA: a chave pública (anon), que fica no site, conseguia INSERIR em telemetry e system_config
--    (e passar da RLS em agents). O painel só LÊ; quem escreve é o sync com a chave secreta (service_role,
--    que ignora estas permissões). Então a chave pública perde toda permissão de escrita, em todas as tabelas.

-- 1) histórico do saldo -----------------------------------------------------------------------------------
create table if not exists public.account_history (
  ts      timestamptz primary key,              -- instante do ponto (UTC)
  balance double precision not null,            -- saldo da conta depois do negócio / na foto
  equity  double precision,                     -- só nas fotos periódicas (kind = 'snapshot')
  kind    text not null default 'snapshot' check (kind in ('deal', 'snapshot'))
);

alter table public.account_history enable row level security;

drop policy if exists "historico do saldo: leitura publica" on public.account_history;
create policy "historico do saldo: leitura publica" on public.account_history
  for select to anon, authenticated using (true);

grant select on public.account_history to anon, authenticated;

-- tempo real (o gráfico recebe os pontos novos sem recarregar)
do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'account_history') then
    alter publication supabase_realtime add table public.account_history;
  end if;
end $$;

-- 2) chave pública só lê ------------------------------------------------------------------------------------
revoke insert, update, delete, truncate on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke insert, update, delete, truncate on tables from anon, authenticated;

-- conferência: deve listar só SELECT (e REFERENCES/TRIGGER, inofensivos) para anon
select table_name, string_agg(privilege_type, ', ' order by privilege_type) as anon_pode
from information_schema.role_table_grants
where grantee = 'anon' and table_schema = 'public'
group by table_name
order by table_name;
