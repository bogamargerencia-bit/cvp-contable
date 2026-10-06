# servicio — procesamiento de corridas (Railway)

FastAPI que envuelve a `cvp_parser`. La web crea la corrida en Supabase y llama a `POST /procesar`
con `Authorization: Bearer $SERVICIO_TOKEN`. El servicio:

1. Toma la corrida con un UPDATE condicional (`pendiente → procesando`). Si ya la tomó otro proceso, no hace nada.
2. Descarga los archivos **vigentes** del período desde Storage y verifica su SHA-256.
3. Arma la entrada del parser:
   - cuenta bancaria: estado de cuenta + libro del sistema;
   - cuenta en divisas: su libro;
   - además, si están: cierre de caja, Kardex y Excel de revisión anterior.
4. Ejecuta `procesar_cliente` → `aplicar` (revisión) → `excel_conciliacion`.
5. Sube el Excel a `{cliente}/{periodo}/corridas/…`, inserta las partidas (montos como texto, nunca float)
   y guarda el resumen y el OK general.

Si algo falta o no se puede leer, la corrida termina en `error` con un mensaje para el analista. Nada se ajusta.

## Railway

| Dónde | Qué poner |
|---|---|
| *Settings → Source → Root Directory* | vacío (raíz del repo) |
| `railway.json` (en la raíz) | ya indica `servicio/Dockerfile` y el chequeo de salud `/salud` |
| *Variables* | las de `servicio/.env.example` |

## Pruebas

```bash
pip install ./parser -r servicio/requirements.txt pytest
python -m pytest servicio/tests
```

Las pruebas con WEI REST y CACAO usan los archivos reales de `parser/tests/fixtures/`, que no están en git.
Si faltan, esas pruebas se saltan.
