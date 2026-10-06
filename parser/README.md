# parser — lectura y cuadre de estados de cuenta

Servicio en Python de CVP Contable. Fase 1: PDF → movimientos → cuadre → comisiones → Excel.

## Estructura

```
parser/
  cvp_parser/
    montos.py   Conversión a Decimal (formato VE 1.234,56 y US 1,234.56). Rechaza float y no redondea.
    modelo.py   Modelo común: Movimiento, TotalesBanco, Extracto, ResultadoLectura, interfaz Lector.
    cuadre.py   Validaciones contra el banco. Devuelve estado: cuadra / requiere_revision / no_cuadra.
    lectores/   banco_100.py (PDF), bnc.py (.xls), banplus.py (.xlsx y .xls), plaza.py (PDF).
                Pendientes: activo.py, mercantil.py
    clientes.py Configuración por cliente: columnas de caja → banco/modo, asientos resumen → columnas.
    sistema.py  Export del libro de bancos del sistema (US$, Referencia = monto en Bs.).
    naturaleza.py   Clasificación por naturaleza + detección de traslados entre cuentas propias.
    conciliacion.py Banco vs. libro: exacto, agrupado, componentes, diferencia de monto,
                    sentido invertido, registrado en otro banco, pistas.
    ventas.py   Cierre de caja diario (Excel VENTAS): medios de pago por banco y desglose desde fórmulas.
    conciliacion_caja.py  Caja ↔ banco (POS por lote D+2, pago móvil por sumando/fraccionado/dígito)
                          y caja ↔ asientos resumen del libro (US$ del mes o hasta una fecha).
    revision.py Ciclo de revisión: pendientes con código estable, lectura de decisiones del Excel
                reintroducido, Resuelto / Cerrado / Advertencia, OK general e historial.
    kardex.py   Kardex de tesorería en divisas (ingresos del día, pagos, fondo, VIENEN/DISPONIBLE).
    divisas.py  Cuentas en US$ (efectivo, Zelle, USDT, fondo): ventas ↔ libro ↔ Kardex y saldos;
                venta de dólares ↔ libro del banco.
    proceso.py  Orquesta un cliente/período completo (también por línea de comandos).
    exportar.py Excel de conciliación (Resumen, Naturaleza, Pendientes, Asientos resumen, Banco x, Libro x).
  tests/
    fixtures/   PDF reales y sus resultados esperados. NO se suben a git (datos de terceros).
```

## Reglas

- Ningún monto pasa por `float`. Todo es `Decimal` con exactamente 2 decimales.
- El cuadre compara exacto, sin tolerancia. Nada se ajusta: las diferencias se informan con línea y monto.
- Estados:
  - **cuadra**: todo verificado al céntimo.
  - **requiere_revision**: cuadra, pero hay montos deducidos (no impresos por el banco) o datos que el banco no trae para verificar.
  - **no_cuadra**: al menos una diferencia o una línea que el lector no pudo leer.

## Validaciones del cuadre

1. Errores de lectura del lector.
2. Saldo línea por línea (si el banco imprime saldo en esa línea). Tras una diferencia continúa desde el saldo del banco.
3. Saldo anterior, total débitos, total créditos, nº de operaciones (o nº de débitos y créditos por separado) y nuevo saldo contra el resumen del banco.
4. Continuidad entre meses de la misma cuenta, y extractos duplicados.

## Uso

```
pip install -e ".[dev]"
pytest
```

## Conciliación de un cliente (ejemplo WEI REST, agosto 2026)

```
python -m cvp_parser.proceso --cliente "WEI REST" --periodo 2026-08 \
  --banco 100_BANCO edo_100.pdf sistema_100.xls \
  --banco BNC edo_bnc.xls sistema_bnc.xls \
  --banco BANPLUS edo_banplus.xlsx sistema_banplus.xls \
  --ventas VENTAS_AGOSTO_2026.xlsx \
  -o WEI_REST_2026-08_conciliacion.xlsx
```

Parámetros: ventana de fechas ±5 días (`--dias`), tolerancia de diferencia de monto Bs. 1,00.
Una "Diferencia de monto" se empareja pero NO cuenta como conciliada.

## Ciclo de revisión

1. Corrida 1: el Excel trae la hoja **Revisión** (primera hoja) con cada partida a revisar y un código
   estable (p. ej. `BNC-L-807A6B`). El analista completa solo Decisión / Comentario / Revisado por:
   - **Aceptar**: lo propuesto es correcto.
   - **Justificado**: correcto así (comentario obligatorio).
   - **Corregido en el sistema**: se corrigió el asiento; en la corrida siguiente debe desaparecer.
2. Corrida N: se vuelve a correr con `--revision <excel de la corrida anterior>` y, si hubo correcciones,
   con el export nuevo del sistema (acepta .xls o .xlsx).
   - Partida que ya no aparece → **Resuelta**.
   - Aceptar / Justificado válidos → **Cerrada** (la decisión se arrastra).
   - «Corregido en el sistema» pero sigue igual → **advertencia**.
   - Justificado sin comentario o sin revisor → **Decisión incompleta**.
3. **OK general** = todos los bancos cuadran y no queda ninguna partida abierta. Lo cierra el analista.
   El historial de decisiones se acumula en la hoja **Historial**; la hoja oculta **_control** identifica
   cliente, período y corrida (un archivo de otro cliente o período se rechaza).

## Configuración por cliente (clientes.py)

Cuando un cliente no está configurado, las columnas de caja se detectan por el nombre (WEI REST).
CACAO tiene configuración propia: «PUNTO CACAO» = POS de Banplus + Plaza por total del mes,
«PAGO MOVIL» = Banplus por total diario (fin de semana → lunes), y qué asientos resumen del libro
corresponden a cada columna. Modos de cruce: desglose / lote / total_diario / total_mes.

## Correcciones de fecha en el cierre de caja

Si una fila de caja tiene la fecha mal escrita (p. ej. dos «27/08» y ningún «26/08», y el monto coincide
exacto con los cobros del banco del 26/08), la hoja Revisión trae la partida
«Caja: corrección de fecha propuesta». Si el analista la marca «Aceptar», en la corrida siguiente la app
lee esa fila con la fecha corregida (el Excel de ventas no se modifica), lo deja anotado en la hoja
Cierre de caja y en _control, y la sigue aplicando en las corridas posteriores.

## Cuentas en divisas (efectivo $, Zelle, USDT, fondo de efectivo)

```
python -m cvp_parser.proceso ... --ventas VENTAS.xlsx \
  --divisa "Efectivo $" SISTEMA_EFECTIVO.XLS --divisa Zelle SISTEMA_ZELLE.XLS \
  --divisa USDT SISTEMA_USDT.XLS --divisa Fondo SISTEMA_FONDO_EFECTIVO.XLS --kardex KARDEX.xlsx
```

Por cuenta: ventas del mes = asiento «VTAS» del libro; ventas día a día = Kardex; cada movimiento del
libro contra el Kardex (exacto, agrupado, «incluido en la fila del día»); saldo inicial/final = VIENEN /
DISPONIBLE. Las cuentas se configuran por cliente en clientes.py (columna de ventas, medio del Kardex).
