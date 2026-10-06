# CVP Contable — instrucciones para Claude

- Responde en español.
- Antes de escribir código, confirma en qué fase estamos y qué archivo o pieza vamos a tocar.
- Prioriza la exactitud: todo debe cuadrar al céntimo, y si algo no cuadra, dilo explícitamente en lugar de ajustarlo.
- Ten presente que son datos bancarios de terceros.

## Reglas técnicas

- Montos: `numeric(18,2)` en Postgres y `Decimal` en Python (`cvp_parser.montos`). Nunca `float`.
  En la web, los montos se leen como texto (`monto::text`) y se formatean sin convertir a `number`.
- RLS en toda tabla nueva. Las funciones de acceso viven en el esquema `privado` (no expuesto por la API).
- `SUPABASE_SECRET_KEY` solo en `web/src/lib/supabase/admin.ts` (importa `server-only`).
- Los archivos reales de clientes van en `parser/tests/fixtures/` (ignorado por git). Nunca en commits ni en zip.
- `web/` usa Next.js 16: el middleware se llama `proxy.ts`, y `params`, `searchParams` y `cookies()` son asíncronos.
  Lee `web/node_modules/next/dist/docs/` antes de usar una API que no conozcas.
- Después de cambiar el esquema: corre los advisors de Supabase y `supabase/pruebas/rls.sql`.
