-- Un usuario nuevo nace INACTIVO: no ve nada hasta que un admin lo active.
-- (Si alguien lograra registrarse por su cuenta, no tendría acceso a datos de clientes.)
alter table public.perfiles alter column activo set default false;

-- Los usuarios que crea el admin desde la web se activan al crearse (la web usa service_role
-- y luego actualiza el perfil); el perfil automático solo copia email y nombre.
