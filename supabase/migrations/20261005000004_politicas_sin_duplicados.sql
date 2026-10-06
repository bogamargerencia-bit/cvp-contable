-- PENDIENTE (no aplicada): requiere confirmar sentencias drop policy en Supabase.
-- Solo rendimiento: separa las políticas «admin for all» por acción. No cambia quién ve qué.

-- ---------------------------------------------------------------- políticas sin duplicados
drop policy perfiles_update_admin  on public.perfiles;
drop policy perfiles_update_propio on public.perfiles;
-- El trigger proteger_perfil impide que un no-admin cambie rol o activo.
create policy perfiles_update on public.perfiles for update to authenticated
  using (id = (select auth.uid()) or privado.es_admin())
  with check (id = (select auth.uid()) or privado.es_admin());

do $$
declare t text; p text; acc text;
begin
  foreach t in array array['configuracion', 'analista_clientes', 'clientes', 'cuentas'] loop
    p := case t when 'analista_clientes' then 'asignaciones' else t end;
    execute format('drop policy %I on public.%I', p || '_admin', t);
    execute format('create policy %I on public.%I for insert to authenticated with check (privado.es_admin())',
                   p || '_insert', t);
    execute format('create policy %I on public.%I for update to authenticated using (privado.es_admin()) with check (privado.es_admin())',
                   p || '_update', t);
    execute format('create policy %I on public.%I for delete to authenticated using (privado.es_admin())',
                   p || '_delete', t);
  end loop;
end $$;

