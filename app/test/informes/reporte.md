# Reporte de evaluación — Informe de Atención

- Casos comparados: **3**
- Aciertos de veredicto: **1/3** (accuracy = 0.333)

## Matriz de confusion (real -> generado)

- FUNDADO->FUNDADO: 1
- FUNDADO->INFUNDADO: 2

## Por caso

| sum | real | generado | acierto | estable | obj (det) | lectura vista | alerta |
|-----|------|----------|---------|---------|-----------|---------------|--------|
| 7686 | FUNDADO | FUNDADO | OK | si | 6 (6) | - |  |
| 489 | FUNDADO | INFUNDADO | FALLA | si | 5 (5) | - |  |
| 7175 | FUNDADO | INFUNDADO | FALLA | si | 7 (7) | - |  |