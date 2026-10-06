# web — CVP Contable

Next.js 16 (App Router) + Supabase SSR. Ver el README de la raíz para la puesta en marcha.

- `src/proxy.ts`: renueva la sesión y manda a `/login` a quien no la tenga.
- `src/lib/sesion.ts`: `perfilActual()` y `exigirAdmin()`; los usuarios inactivos van a `/inactivo`.
- `src/lib/supabase/admin.ts`: clave secreta, solo servidor (crear usuarios).
- Rutas: `/login`, `/` (clientes), `/clientes/nuevo`, `/clientes/[id]`, `/admin/usuarios`, `/cuenta`.
