# APP CVP CONTABLE

Herramienta interna de CVP para leer estados de cuenta, conciliarlos con el libro del sistema y preparar la
revisión de los analistas. **Uso exclusivo del personal de CVP (admin + 4 analistas); los clientes no tienen acceso.**

| Carpeta | Qué es | Estado |
|---|---|---|
| `parser/` | Paquete Python `cvp_parser`: lectores de bancos, cuadre, conciliación, caja, divisas, Excel de revisión | Listo (87 pruebas) |
| `supabase/migrations/` | Esquema Postgres, RLS, auditoría, storage privado | Aplicado al proyecto `cvp-contable` |
| `supabase/pruebas/rls.sql` | Prueba de permisos (no deja datos) | 14/14 OK |
| `web/` | Next.js 16 (App Router) en Vercel: login, roles, clientes, cuentas, períodos, usuarios | Paso 1 listo |
| `servicio/` | FastAPI que envuelve al parser (Railway) | Paso 2 — pendiente |

## Reglas que no se negocian

- **Exactitud al céntimo.** Montos en `numeric(18,2)` en la base y `Decimal` en Python; nunca `float`.
  Si algo no cuadra se informa, no se ajusta.
- **Datos bancarios de terceros.**
  - RLS en todas las tablas.
  - Bucket de Storage privado.
  - Los números de cuenta se muestran enmascarados.
  - Los archivos reales de clientes (`parser/tests/fixtures/`) nunca van a git ni a los zip.
- **Claves secretas solo en el servidor.** La `SUPABASE_SECRET_KEY` y la clave de la API de Claude nunca llevan el
  prefijo `NEXT_PUBLIC_` ni salen del servidor.

## Roles y permisos

| Acción | Analista | Admin |
|---|---|---|
| Ver clientes, cuentas, períodos | ✔ (todos, o solo los asignados si se activa `asignacion_por_analista`) | ✔ |
| Crear clientes y cuentas | — | ✔ |
| Abrir y cerrar períodos | ✔ | ✔ |
| Reabrir un período cerrado | — | ✔ |
| Crear usuarios, cambiar rol, activar | — | ✔ |
| Ver auditoría | — | ✔ |

Un usuario nuevo nace **inactivo** y no ve nada hasta que un admin lo active.
Los que crea el admin desde la web nacen activos.

## Puesta en marcha (una sola vez)

1. **Supabase → Authentication → Sign In / Providers:** desactivar *Allow new users to sign up*.
   Las cuentas las crea el admin.
2. **Primer administrador:**
   - En *Authentication → Users → Add user*, crea tu usuario con *Auto Confirm User*.
   - Luego, en el SQL Editor:
     ```sql
     update public.perfiles set rol = 'admin', activo = true, nombre = 'Tu nombre'
     where email = 'tu-correo@dominio.com';
     ```
3. **Vercel:**
   - Importar el repositorio con *Root Directory* = `web`.
   - Variables de entorno: las de `web/.env.example`. `SUPABASE_SECRET_KEY` sale de *Project Settings → API Keys → Secret keys*.
4. **Supabase → Authentication → URL Configuration:** poner como *Site URL* la URL de Vercel.

## Desarrollo local

```bash
cd web && cp .env.example .env.local   # completar SUPABASE_SECRET_KEY
npm install && npm run dev             # http://localhost:3000

cd parser && pip install -e . && pytest
```

## Migraciones

| Archivo | Contenido | Estado |
|---|---|---|
| `…0001_esquema_base` | Tablas | Aplicada |
| `…0002_seguridad` | Funciones de acceso, triggers, auditoría, RLS, bucket | Aplicada |
| `…0003_funciones_privadas_e_indices` | Funciones de acceso en el esquema `privado` (fuera de la API), índices de claves foráneas | Aplicada |
| `…0004_politicas_sin_duplicados` | Separa las políticas «admin para todo» por acción (solo rendimiento) | **Pendiente**: requiere confirmar `drop policy` |
| `…0005_perfiles_inactivos_por_defecto` | Perfiles nuevos inactivos | Aplicada |
