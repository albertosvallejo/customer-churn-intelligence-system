# Attempts

Los logs disponibles para este job son acumulados/históricos.
No se inventan cortes exactos por intento porque el runner aún no registraba `attempt_id` separado.
Descripción disponible: single clean-source lifecycle.

Para validaciones futuras, el sistema de evidencia reserva `attempts/001/`, `attempts/002/`, etc.
La separación automática requiere que el runner escriba un identificador de intento al iniciar cada `handle`.
