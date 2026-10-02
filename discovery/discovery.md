# Discovery — turnos-odontología

**Fecha**: 2026-10-01
**Fuentes investigadas**: 19 sistemas en `discovery/sources/competidores-saas-ar.md` (criterio: solo evidencia pública, sin evidencia = "No evidenciado", fecha consulta 2026-10-01) + verificación fresca 2026-10-01 (DentalSoft AR https://dentalsoft.com.ar, Dentalink +15k clientes/+20 países, AgendaPro caso odontológico Rosario con cancelación 3h, Dentiqa AR https://dentiqa.app/ar con chatbot IA WA y precios ARS, comparativa Gestión Dental 2026-08-10).

## 1. Problema que resuelve

Consultorios/clínicas odontológicas coordinan turnos por WhatsApp/papel, lo que
genera dobles reservas, huecos vacíos por ausentismo y horas perdidas de la
secretaria confirmando manualmente cada turno.

## 2. Usuarios / roles

- **Paciente**: reserva un turno sin llamar ni escribir.
- **Odontólogo**: ve su agenda del día/semana.
- **Secretaria**: gestiona agenda, crea/cancela/reprograma por teléfono/presencial.
- Escala: multi-odontólogo desde día 1 (clínica, no sillón único).

## 3. Casos de uso

1. Como paciente, quiero ver los horarios libres por odontólogo para reservar
   sin tener que preguntar por WhatsApp.
2. Como secretaria, quiero ver la agenda día/semana por odontólogo para crear
   y mover turnos.
3. Como odontólogo, quiero ver mi agenda del día para saber a quién atiendo.
4. Como paciente, quiero cancelar/reprogramar con anticipación para liberar el
   horario.

## 4. Competidores / soluciones existentes

Solución actual: manual (WhatsApp + papel/planilla). Relevamiento exhaustivo
en `discovery/sources/competidores-saas-ar.md`: tabla comparativa de 19
sistemas ordenados por relevancia AR (secciones A–D: tabla, matriz ponderada
Turnos25/Clínica20/Integ15/Admin15/Exp10/Seg10/Precio5, análisis competitivo,
recomendación 5 demos + 3 refs UX + MVP).

Top AR: DentalSoft AR (nube, odontograma SVG, WA Pro USD 0,026/msg, $30–60k
ARS +$10k/prof, gratis 6m/50 turnos); Dentalink/Healthatom CL (+15k clientes
afirmación, sobreamiento paralelo, solo cotización); AgendaPro CL (generalista,
$13,9–44,9k ARS, MP 2%/1% comprobado, FE AR próximamente); Docturno AR (bot WA
24x7 afirmación, ~$20–35k/mes); Doctoralia Pro (marketplace, $25–55k ARS anual).
Hallazgo nuevo 2026-10-01: Dentiqa AR (chatbot IA WA, odonto+perio, pipeline
CRM, AES-256+audit, $135k/$225k/$375k ARS vía MP, https://dentiqa.app/ar).

**Notas**: sin precio público (Dentalink/Dentidesk) = vacío AR; WA suele ser
costo extra o pendiente; FE AFIP/ARCA ausente o parcial; OS sin liquidación
salvo Dentalink módulo y DentalSoft. Diferenciá siempre hecho comprobado vs
afirmación comercial — detalle por sistema en el archivo de fuentes.

## 5. Funcionalidades necesarias

- Agenda por odontólogo con vista día/semana.
- Reserva de turno online.
- Cancelación y reprogramación de turno.
- Gestión secretaria (alta manual, bloqueo de horarios).

## 6. Funcionalidades opcionales

- Recordatorio automático por WhatsApp 24hs antes + confirmación.
- Historia clínica / odontograma (explícitamente fuera de v1).
- Pagos/señas online (no requerido v1).

## 7. Reglas de negocio

- Un odontólogo no puede tener dos turnos superpuestos.
- No se puede cancelar/reprogramar con menos de anticipación mínima configurable
  (supuesto inicial: 24hs, a confirmar — AgendaPro caso real usa 3hs).
- Duraciones por tratamiento a definir (ej. limpieza 30m, conducto 60m).

## 8. Integraciones

- WhatsApp para recordatorio/confirmación (v1 solo envío, no bot conversacional).
- Sin Google Calendar obligatorio en v1.

## 9. Restricciones

- Sin stack impuesto (supuesto — a validar en kb-creator).
- Tiene que andar bien en celular — reserva mayormente desde teléfono.
- Presupuesto acotado clínica chica/mediana.

## 10. Riesgos

- **Supuesto sin probar**: si la agenda no se mantiene actualizada
  (bloqueos, vacaciones, duraciones reales), el sistema muestra huecos falsos
  — riesgo principal elegido por el usuario.
- **Adopción**: pacientes pueden seguir prefiriendo WhatsApp por costumbre.
- **No-show**: recordatorio puede no reducir ausentismo lo suficiente.

## 11. Preguntas abiertas

- ¿Login para paciente o alcanza con nombre + teléfono por turno?
- ¿Anticipación mínima de cancelación definitiva? ¿24h o 2h?
- ¿Duraciones fijas por tratamiento desde v1 o duración única configurable?
- ¿Stack impuesto? ¿Plazo de lanzamiento?
