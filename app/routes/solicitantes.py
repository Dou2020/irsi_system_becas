from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from sqlalchemy import func, or_
from app.models.enums import Programa
from app.models.solicitante import Solicitante
from app.models.historial_estado import HistorialEstado
from app.forms.solicitante_forms import SolicitanteForm
from app.utils.authorization import require_role
from app.models.enums import EstadoSolicitud
from app.services.solicitantes_service import (
    detectar_reaplicacion,
    cambiar_estado_solicitante,
    validar_documentos
)
from werkzeug.utils import secure_filename
import os

solicitantes_bp = Blueprint('solicitantes', __name__, template_folder='../templates/solicitantes')

@solicitantes_bp.route('/', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def list_solicitantes():
    page = request.args.get('page', 1, type=int)
    filtros = {
        'nombre': request.args.get('nombre', ''),
        'programa': request.args.get('programa', ''),
        'estado': request.args.get('estado', ''),
        'pais': request.args.get('pais', '')
    }

    form = SolicitanteForm()
    pagination = Solicitante.buscar_avanzado(filtros, page=page, per_page=10)
    
    # AGREGAR ESTAS LÍNEAS PARA LAS ESTADÍSTICAS:
    estadisticas = {
        'en_revision': Solicitante.query.filter_by(estado=EstadoSolicitud.EN_REVISION).count(),
        'aprobados': Solicitante.query.filter_by(estado=EstadoSolicitud.APROBADO).count(),
        'rechazados': Solicitante.query.filter_by(estado=EstadoSolicitud.RECHAZADO).count(),
        'registrados': Solicitante.query.filter_by(estado=EstadoSolicitud.REGISTRADO).count()
    }

    return render_template(
        'solicitantes/list.html',
        pagination=pagination,
        filtros=filtros,
        form=form,
        estadisticas=estadisticas  # AGREGAR ESTA LÍNEA
    )

@solicitantes_bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_role('Administrador', 'Director', 'Asistente')
def create_solicitante():
    form = SolicitanteForm()

    if request.method == 'POST':
        # Entramos aquí cada vez que le dan a “Guardar”
        if form.validate_on_submit():
            datos = form.data

            # 1) Detección de reaplicación
            previo = detectar_reaplicacion(datos['emails'], datos['documento'])
            if previo:
                flash('Nota: ya existe una aplicación previa con este email o documento. Se creará una nueva entrada.', 'info')

            # 2) Crear el objeto Solicitante
            solicitante = Solicitante(
                nombre=datos['nombre'],
                emails=datos['emails'],
                documento=datos['documento'],
                fecha_nacimiento=datos['fecha_nacimiento'],
                genero=datos['genero'],
                pais=datos['pais'],
                ciudad=datos['ciudad'],
                telefonos=datos['telefonos'],
                nivel_educativo=datos['nivel_educativo'],
                institucion=datos['institucion'],
                promedio=datos['promedio'],
                experiencia_tech=datos['experiencia_tech'],
                situacion_laboral=datos['situacion_laboral'],
                ingresos=datos['ingresos'],
                acceso_tecnologia=datos['acceso_tecnologia'],
                dependientes=datos['dependientes'],
                programa_solicitado=datos['programa_solicitado'],
                modalidad=datos['modalidad'],
                disponibilidad=datos['disponibilidad'],
                motivacion=datos['motivacion'],
                objetivos=datos['objetivos'],
                estado= EstadoSolicitud.EN_REVISION,
                fecha_registro=datetime.utcnow(),
                fecha_actualizacion=datetime.utcnow()
            )
            db.session.add(solicitante)
            db.session.commit()

            # 3) Crear historial de estado
            cambiar_estado_solicitante(solicitante.id, EstadoSolicitud.EN_REVISION, current_user.id)

            flash('Solicitante creado exitosamente.', 'success')
            return redirect(url_for('solicitantes.list_solicitantes'))

        else:
            # form.validate_on_submit() devolvió False → hay errores
            # Mostramos mensajes debajo de cada campo y recargamos el form
            for campo, errores in form.errors.items():
                for error in errores:
                    flash(f'Error en "{getattr(form, campo).label.text}": {error}', 'danger')

            # NOTA: si quieres que el usuario vea en qué step estaba cuando falló la validación,
            # tendrías que guardar un campo oculto <input name="current_step" …> o similares.
            # De momento, recargamos el form en el paso 1 y mostramos los errores.

    # Si es GET o hubo errores de validación, renderizamos el formulario
    return render_template('solicitantes/form.html', form=form)

@solicitantes_bp.route('/<int:solicitante_id>', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def detail_solicitante(solicitante_id):
    sol = Solicitante.query.get_or_404(solicitante_id)

    historial = HistorialEstado.query.filter_by(solicitante_id=solicitante_id).order_by(HistorialEstado.fecha.desc()).all()    
    try:
        documentos = sol.listar_documentos()
    except AttributeError:
        documentos = []

    # contar reaplicaciones
    reaplicaciones = Solicitante.query.filter(
        (Solicitante.emails == sol.emails) | 
        (Solicitante.documento == sol.documento)
    ).order_by(Solicitante.fecha_registro.asc()).all()
    mostrar_compare = len(reaplicaciones) > 1
    return render_template(
        'solicitantes/detail.html',
        solicitante=sol,
        historial=historial,
        documentos=documentos,
        EstadoSolicitud=EstadoSolicitud,
        mostrar_compare=mostrar_compare
    )

@solicitantes_bp.route('/<int:solicitante_id>/edit', methods=['GET', 'POST'])
@login_required
@require_role('Administrador', 'Director', 'Asistente')
def edit_solicitante(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    form = SolicitanteForm(obj=solicitante)
    if request.method == 'POST' and form.validate():
        datos = form.data
        solicitante.nombre = datos['nombre']
        solicitante.emails=datos['emails']
        solicitante.documento = datos['documento']
        solicitante.fecha_nacimiento = datos['fecha_nacimiento']
        solicitante.genero = datos['genero']
        solicitante.pais = datos['pais']
        solicitante.ciudad = datos['ciudad']
        solicitante.telefonos = datos['telefonos']
        solicitante.nivel_educativo = datos['nivel_educativo']
        solicitante.institucion = datos['institucion']
        solicitante.promedio = datos['promedio']
        solicitante.experiencia_tech = datos['experiencia_tech']
        solicitante.situacion_laboral = datos['situacion_laboral']
        solicitante.ingresos = datos['ingresos']
        solicitante.acceso_tecnologia = datos['acceso_tecnologia']
        solicitante.dependientes = datos['dependientes']
        solicitante.programa_solicitado = datos['programa_solicitado']
        solicitante.modalidad = datos['modalidad']
        solicitante.disponibilidad = datos['disponibilidad']
        solicitante.motivacion = datos['motivacion']
        solicitante.objetivos = datos['objetivos']
        solicitante.fecha_actualizacion = datetime.utcnow()
        db.session.commit()
        flash('Solicitante actualizado correctamente.', 'success')
        return redirect(url_for('solicitantes.detail_solicitante', solicitante_id=solicitante.id))
    return render_template('solicitantes/form.html', form=form, solicitante=solicitante)

@solicitantes_bp.route('/<int:solicitante_id>/change_state', methods=['POST'])
@login_required
@require_role('Administrador', 'Director')
def change_state(solicitante_id):
    nuevo_estado = request.form.get('estado')
    comentario = request.form.get('comentario', '')
    cambiar_estado_solicitante(solicitante_id, nuevo_estado, current_user.id, comentario)
    flash(f'Estado cambiado a {nuevo_estado}.', 'success')
    return redirect(url_for('solicitantes.detail_solicitante', solicitante_id=solicitante_id))

@solicitantes_bp.route('/upload/<int:solicitante_id>', methods=['POST'])
@login_required
@require_role('Administrador', 'Director', 'Asistente')
def upload_document(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    file = request.files.get('documento')
    if not file:
        flash('No se seleccionó ningún archivo.', 'danger')
        return redirect(url_for('solicitantes.detail_solicitante', solicitante_id=solicitante_id))
    filename = secure_filename(file.filename)
    if not validar_documentos(filename):
        flash('Formato de archivo no permitido.', 'danger')
        return redirect(url_for('solicitantes.detail_solicitante', solicitante_id=solicitante_id))
    upload_folder = current_app.config.get('UPLOAD_FOLDER_SOLICITANTES')
    camino = os.path.join(upload_folder, str(solicitante_id))
    os.makedirs(camino, exist_ok=True)
    ruta_archivo = os.path.join(camino, filename)
    file.save(ruta_archivo)
    #solicitante.agregar_documento(filename)
    db.session.commit()
    flash('Documento subido exitosamente.', 'success')
    return redirect(url_for('solicitantes.detail_solicitante', solicitante_id=solicitante_id))


@solicitantes_bp.route('/<int:solicitante_id>/compare', methods=['GET', 'POST'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def compare_solicitante(solicitante_id):
    # 1) Recuperamos la aplicación actual
    actual = Solicitante.query.get_or_404(solicitante_id)

    # 2) Buscamos todas las aplicaciones de esta persona (mismo email O mismo documento)
    todas = Solicitante.query.filter(
        (Solicitante.emails == actual.emails) |
        (Solicitante.documento == actual.documento)
    ).order_by(Solicitante.fecha_registro.asc()).all()

    # 3) Inicializamos las dos a comparar
    app1 = actual
    app2 = None

    # 4) Si es POST, tomamos los IDs elegidos en el formulario
    if request.method == 'POST':
        id1 = int(request.form.get('app1'))
        id2 = int(request.form.get('app2'))
        app1 = next((s for s in todas if s.id == id1), actual)
        app2 = next((s for s in todas if s.id == id2), None)

    return render_template(
        'solicitantes/compare.html',
        aplicaciones=todas,
        app1=app1,
        app2=app2
    )


@solicitantes_bp.route('/exportar', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente')
def exportar_solicitantes():
    import csv
    from flask import Response
    from io import StringIO
    
    # Obtener filtros de la URL
    filtros = {
        'nombre': request.args.get('nombre', ''),
        'programa': request.args.get('programa', ''),
        'estado': request.args.get('estado', ''),
        'pais': request.args.get('pais', '')
    }
    
    # Obtener todos los resultados (sin paginación)
    query = Solicitante.query
    if filtros.get('nombre'):
        query = query.filter(Solicitante.nombre.ilike(f"%{filtros['nombre']}%"))
    if filtros.get('programa'):
        query = query.filter(Solicitante.programa_solicitado == filtros['programa'])
    if filtros.get('estado'):
        try:
            estado_enum = EstadoSolicitud[filtros['estado']]
            query = query.filter(Solicitante.estado == estado_enum)
        except KeyError:
            pass
    if filtros.get('pais'):
        query = query.filter(Solicitante.pais == filtros['pais'])
    
    solicitantes = query.order_by(Solicitante.fecha_registro.desc()).all()
    
    # Crear CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Encabezados
    writer.writerow([
        'ID', 'Nombre', 'Documento', 'Email', 'Teléfono', 'País', 
        'Programa', 'Estado', 'Fecha Registro'
    ])
    
    # Datos
    for sol in solicitantes:
        writer.writerow([
            sol.id,
            sol.nombre,
            sol.documento,
            sol.emails,
            sol.telefonos,
            sol.pais.value if sol.pais else '',
            sol.programa_legible,
            sol.estado_legible,
            sol.fecha_registro.strftime('%d/%m/%Y %H:%M')
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=solicitantes.csv"}
    )

@solicitantes_bp.route('/<int:solicitante_id>/documentos')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def ver_documentos(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    documentos = solicitante.listar_documentos()
    
    return render_template(
        'solicitantes/documentos.html',
        solicitante=solicitante,
        documentos=documentos
    )


@solicitantes_bp.route('/<int:solicitante_id>/historial')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def ver_historial(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    # Necesitarás descomentar la relación en el modelo
    historial = HistorialEstado.query.filter_by(solicitante_id=solicitante_id)\
                                   .order_by(HistorialEstado.fecha_cambio.desc()).all()
    
    return render_template(
        'solicitantes/historial.html',
        solicitante=solicitante,
        historial=historial
    )


@solicitantes_bp.route('/<int:solicitante_id>/eliminar', methods=['POST'])
@login_required
@require_role('Administrador', 'Director')
def eliminar_solicitante(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    
    try:
        # Eliminar archivos asociados si existen
        upload_folder = current_app.config.get('UPLOAD_FOLDER_SOLICITANTES')
        if upload_folder:
            import shutil
            carpeta = os.path.join(upload_folder, str(solicitante.id))
            if os.path.exists(carpeta):
                shutil.rmtree(carpeta)
        
        db.session.delete(solicitante)
        db.session.commit()
        flash('Solicitante eliminado exitosamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash('Error al eliminar el solicitante', 'error')
        current_app.logger.error(f"Error eliminando solicitante {solicitante_id}: {e}")
    
    return redirect(url_for('solicitantes.list_solicitantes'))


@solicitantes_bp.route('/<int:solicitante_id>/documentos/<filename>/descargar')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def descargar_documento(solicitante_id, filename):
    from flask import send_file
    
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    upload_folder = current_app.config.get('UPLOAD_FOLDER_SOLICITANTES')
    
    if not upload_folder:
        flash('Configuración de archivos no disponible', 'error')
        return redirect(url_for('solicitantes.list_solicitantes'))
    
    archivo_path = os.path.join(upload_folder, str(solicitante.id), secure_filename(filename))
    
    if not os.path.exists(archivo_path):
        flash('Archivo no encontrado', 'error')
        return redirect(url_for('solicitantes.list_solicitantes'))
    
    return send_file(archivo_path, as_attachment=True)

@solicitantes_bp.route('/<int:solicitante_id>/documentos/<filename>/preview')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def preview_documento(solicitante_id, filename):
    from flask import send_file
    
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    upload_folder = current_app.config.get('UPLOAD_FOLDER_SOLICITANTES')
    
    if not upload_folder:
        flash('Configuración de archivos no disponible', 'error')
        return redirect(url_for('solicitantes.list_solicitantes'))
    
    archivo_path = os.path.join(upload_folder, str(solicitante.id), secure_filename(filename))
    
    if not os.path.exists(archivo_path):
        flash('Archivo no encontrado', 'error')
        return redirect(url_for('solicitantes.list_solicitantes'))
    
    return send_file(archivo_path, as_attachment=False)


@solicitantes_bp.route('/<int:solicitante_id>/historial/ajax')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def obtener_historial_ajax(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    # Necesitarás descomentar la relación en el modelo
    historial = HistorialEstado.query.filter_by(solicitante_id=solicitante_id)\
                                   .order_by(HistorialEstado.fecha.desc()).all()
    
    historial_data = []
    for h in historial:
        historial_data.append({
            'estado_nuevo': h.estado.value,
            'fecha_cambio': h.fecha.strftime('%d/%m/%Y %H:%M'),
            'usuario': h.usuario.nombre if h.usuario else 'Sistema',
            'comentario': h.comentario or ''
        })
    
    return jsonify({
        'success': True,
        'solicitante': {
            'id': solicitante.id,
            'nombre': solicitante.nombre,
            'estado_actual': solicitante.estado_legible
        },
        'historial': historial_data
    })


@solicitantes_bp.route('/<int:solicitante_id>/documentos/ajax')
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def obtener_documentos_ajax(solicitante_id):
    solicitante = Solicitante.query.get_or_404(solicitante_id)
    documentos = solicitante.listar_documentos()
    
    return jsonify({
        'success': True,
        'solicitante': {
            'id': solicitante.id,
            'nombre': solicitante.nombre,
            'documento': solicitante.documento
        },
        'documentos': documentos
    })


@solicitantes_bp.route('/import-csv', methods=['GET', 'POST'])
@login_required
@require_role('Administrador', 'Asistente')
def import_csv():
    if request.method == 'POST':
        # Verificar que se subió un archivo
        if 'csv_file' not in request.files:
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        file = request.files['csv_file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo', 'danger')
            return redirect(request.url)
        
        if not file.filename.lower().endswith('.csv'):
            flash('Solo se permiten archivos CSV', 'danger')
            return redirect(request.url)
        
        try:
            import csv
            import io
            from app.models.enums import Genero, Pais, Programa, Modalidad
            
            # Leer el archivo CSV
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            
            importados = 0
            errores = []
            
            for row_num, row in enumerate(csv_reader, start=2):  # Empezar en 2 porque la fila 1 son headers
                try:
                    # Validar campos obligatorios
                    campos_obligatorios = ['nombre', 'documento', 'fecha_nacimiento', 'genero', 'pais', 'ciudad', 'nivel_educativo', 'institucion', 'programa_solicitado', 'modalidad']
                    for campo in campos_obligatorios:
                        if not row.get(campo, '').strip():
                            raise ValueError(f"Campo obligatorio '{campo}' está vacío")
                    
                    # Convertir fecha de nacimiento
                    try:
                        fecha_nac = datetime.strptime(row['fecha_nacimiento'], '%Y-%m-%d').date()
                    except ValueError:
                        try:
                            fecha_nac = datetime.strptime(row['fecha_nacimiento'], '%d/%m/%Y').date()
                        except ValueError:
                            raise ValueError("Formato de fecha inválido. Use YYYY-MM-DD o DD/MM/YYYY")
                    
                    # Convertir enums
                    try:
                        genero = Genero[row['genero'].upper()]
                    except KeyError:
                        raise ValueError(f"Género inválido: {row['genero']}")
                    
                    try:
                        pais = Pais[row['pais'].upper()]
                    except KeyError:
                        raise ValueError(f"País inválido: {row['pais']}")
                    
                    try:
                        programa = Programa[row['programa_solicitado'].upper()]
                    except KeyError:
                        raise ValueError(f"Programa inválido: {row['programa_solicitado']}")
                    
                    try:
                        modalidad = Modalidad[row['modalidad'].upper()]
                    except KeyError:
                        raise ValueError(f"Modalidad inválida: {row['modalidad']}")
                    
                    # Verificar si ya existe
                    existe = Solicitante.query.filter(
                        (Solicitante.documento == row['documento']) |
                        (Solicitante.emails == row.get('emails', ''))
                    ).first()
                    
                    if existe:
                        errores.append(f"Fila {row_num}: Ya existe un solicitante con documento {row['documento']} o email {row.get('emails', '')}")
                    
                    # Crear nuevo solicitante
                    solicitante = Solicitante(
                        nombre=row['nombre'].strip(),
                        documento=row['documento'].strip(),
                        fecha_nacimiento=fecha_nac,
                        genero=genero,
                        pais=pais,
                        ciudad=row['ciudad'].strip(),
                        telefonos=row.get('telefonos', '').strip(),
                        emails=row.get('emails', '').strip(),
                        nivel_educativo=row['nivel_educativo'].strip(),
                        institucion=row['institucion'].strip(),
                        promedio=float(row['promedio']) if row.get('promedio', '').strip() else None,
                        experiencia_tech=row.get('experiencia_tech', '').strip(),
                        situacion_laboral=row.get('situacion_laboral', '').strip(),
                        ingresos=float(row['ingresos']) if row.get('ingresos', '').strip() else None,
                        acceso_tecnologia=row.get('acceso_tecnologia', '').strip(),
                        dependientes=int(row['dependientes']) if row.get('dependientes', '').strip() else None,
                        programa_solicitado=programa,
                        modalidad=modalidad,
                        disponibilidad=row.get('disponibilidad', '').strip(),
                        motivacion=row.get('motivacion', '').strip(),
                        objetivos=row.get('objetivos', '').strip(),
                        estado=EstadoSolicitud.EN_REVISION,
                        fecha_registro=datetime.utcnow(),
                        fecha_actualizacion=datetime.utcnow()
                    )
                    
                    db.session.add(solicitante)
                    db.session.commit()
                    
                    # Crear historial de estado
                    cambiar_estado_solicitante(solicitante.id, EstadoSolicitud.EN_REVISION, current_user.id, "Importado desde CSV")
                    
                    importados += 1
                    
                except Exception as e:
                    errores.append(f"Fila {row_num}: {str(e)}")
                    db.session.rollback()
                    continue
            
            # Mostrar resultados
            if importados > 0:
                flash(f'Se importaron {importados} solicitantes exitosamente', 'success')
            
            if errores:
                flash(f'Se encontraron {len(errores)} errores:', 'warning')
                for error in errores[:10]:  # Mostrar solo los primeros 10 errores
                    flash(error, 'danger')
                if len(errores) > 10:
                    flash(f'... y {len(errores) - 10} errores más', 'danger')
            
            return redirect(url_for('solicitantes.list_solicitantes'))
            
        except Exception as e:
            flash(f'Error al procesar el archivo: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('solicitantes/import_csv.html')


@solicitantes_bp.route('/download-template')
@login_required
@require_role('Administrador', 'Asistente')
def download_template():
    import csv
    from flask import Response
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Encabezados de ejemplo
    headers = [
        'nombre', 'documento', 'fecha_nacimiento', 'genero', 'pais', 'ciudad',
        'telefonos', 'emails', 'nivel_educativo', 'institucion', 'promedio',
        'experiencia_tech', 'situacion_laboral', 'ingresos', 'acceso_tecnologia',
        'dependientes', 'programa_solicitado', 'modalidad', 'disponibilidad',
        'motivacion', 'objetivos'
    ]
    
    writer.writerow(headers)
    
    # Fila de ejemplo
    writer.writerow([
        'Juan Pérez', '12345678', '1995-01-15', 'MASCULINO', 'GUATEMALA', 'Guatemala',
        '12345678', 'juan@email.com', 'Universitario', 'Universidad San Carlos',
        '8.5', 'Conocimientos básicos', 'Estudiante', '2000', 'Computadora propia',
        '2', 'CIBERSEGURIDAD', 'VIRTUAL', 'Tiempo completo',
        'Quiero aprender programación', 'Ser desarrollador web'
    ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=plantilla_solicitantes.csv"}
    )


@solicitantes_bp.route('/reaplicaciones', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def list_reaplicaciones():
    # 1) Traigo todas las solicitudes ordenadas
    todos = (
        Solicitante.query
        .order_by(Solicitante.fecha_registro.asc())
        .all()
    )

    # 2) Formo clusters “union-find–light” en memoria:
    clusters: list[list[Solicitante]] = []
    for s in todos:
        colocado = False
        for grupo in clusters:
            # si coincide email CON ALGUNO del grupo o documento CON ALGUNO
            if (s.emails and any(s.emails == otro.emails for otro in grupo)) \
            or (s.documento and any(s.documento == otro.documento for otro in grupo)):
                grupo.append(s)
                colocado = True
                break
        if not colocado:
            clusters.append([s])

    # 3) Me quedo sólo con los clusters de 2+ solicitudes
    clusters = [g for g in clusters if len(g) > 1]

    # 4) (Opcional) Aplico filtros de mínimos, programa y estado igual que antes…
    min_apps = request.args.get('min_aplicaciones', type=int)
    if min_apps:
        clusters = [g for g in clusters if len(g) >= min_apps]

    prog = request.args.get('programa', '')
    if prog:
        try:
            pe = Programa[prog]
            clusters = [
                [s for s in g if s.programa_solicitado == pe]
                for g in clusters
            ]
            clusters = [g for g in clusters if len(g) > 1]
        except KeyError:
            pass

    est = request.args.get('estado', '')
    if est:
        try:
            ee = EstadoSolicitud[est]
            clusters = [
                [s for s in g if s.estado == ee]
                for g in clusters
            ]
            clusters = [g for g in clusters if len(g) > 1]
        except KeyError:
            pass

    # 5) Preparo la lista para la plantilla
    reaplicaciones = []
    total_apps = 0
    for grupo in clusters:
        ordenado = sorted(grupo, key=lambda x: x.fecha_registro)
        total_apps += len(ordenado)
        reaplicaciones.append({
            'nombre':             ordenado[0].nombre,
            'email':              ordenado[0].emails,
            'documento':          ordenado[0].documento,
            'aplicaciones':       ordenado,
            'primera_aplicacion': ordenado[0],
            'ultima_aplicacion':  ordenado[-1],
            'total_aplicaciones': len(ordenado),
        })

    total_personas       = len(reaplicaciones)
    promedio_reaplicaciones = round(total_apps / total_personas, 1) if total_personas else 0
    max_reaplicaciones     = max((r['total_aplicaciones'] for r in reaplicaciones), default=0)

    return render_template('solicitantes/reaplicaciones.html',
        reaplicaciones=reaplicaciones,
        filtros={
          'min_aplicaciones': request.args.get('min_aplicaciones',''),
          'programa': request.args.get('programa',''),
          'estado':   request.args.get('estado',''),
        },
        total_personas=total_personas,
        total_aplicaciones=total_apps,
        promedio_reaplicaciones=promedio_reaplicaciones,
        max_reaplicaciones=max_reaplicaciones,
        programas_disponibles=list(Programa),
        estados_disponibles=list(EstadoSolicitud),
    )

@solicitantes_bp.route('/reportes', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def reportes():
    from sqlalchemy import func, extract
    from datetime import datetime, timedelta
    
    # Filtros de fecha
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    
    # Query base
    query = Solicitante.query
    mesesNombres = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

    # Aplicar filtros de fecha si existen
    if fecha_inicio:
        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            query = query.filter(Solicitante.fecha_registro >= fecha_inicio_dt)
        except ValueError:
            pass
    
    if fecha_fin:
        try:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Solicitante.fecha_registro < fecha_fin_dt)
        except ValueError:
            pass
    
    # 1. Estadísticas generales
    total_solicitantes = query.count()
    
    estadisticas_estado = db.session.query(
        Solicitante.estado,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.estado).all()
    
    # 2. Distribución por programa
    estadisticas_programa = db.session.query(
        Solicitante.programa_solicitado,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.programa_solicitado).all()
    
    # 3. Distribución por país
    estadisticas_pais = db.session.query(
        Solicitante.pais,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.pais).order_by(func.count(Solicitante.id).desc()).limit(10).all()
    
    # 4. Distribución por género
    estadisticas_genero = db.session.query(
        Solicitante.genero,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.genero).all()
    
    # 5. Registros por mes (últimos 12 meses)
    registros_mensuales = db.session.query(
        extract('year', Solicitante.fecha_registro).label('año'),
        extract('month', Solicitante.fecha_registro).label('mes'),
        func.count(Solicitante.id).label('cantidad')
    ).filter(
        Solicitante.fecha_registro >= datetime.now() - timedelta(days=365),
        Solicitante.id.in_(query.with_entities(Solicitante.id))
    ).group_by(
        extract('year', Solicitante.fecha_registro),
        extract('month', Solicitante.fecha_registro)
    ).order_by('año', 'mes').all()
    
    # 6. Estadísticas de edad
    edad_stats = db.session.query(
        func.avg(extract('year', func.current_date()) - extract('year', Solicitante.fecha_nacimiento)).label('promedio'),
        func.min(extract('year', func.current_date()) - extract('year', Solicitante.fecha_nacimiento)).label('minima'),
        func.max(extract('year', func.current_date()) - extract('year', Solicitante.fecha_nacimiento)).label('maxima')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).first()
    
    # 7. Promedios académicos
    promedios_stats = db.session.query(
        func.avg(Solicitante.promedio).label('promedio'),
        func.min(Solicitante.promedio).label('minimo'),
        func.max(Solicitante.promedio).label('maximo')
    ).filter(
        Solicitante.promedio.isnot(None),
        Solicitante.id.in_(query.with_entities(Solicitante.id))
    ).first()
    
    reaplicaciones_stats = {
        'total_personas_con_reaplicaciones': 0,
        'total_reaplicaciones': 0,
        'promedio_reaplicaciones': 0
    }

    # Subconsulta para sólo los IDs que ya vienen filtrados por fecha u otros criterios
    ids_filtrados = query.with_entities(Solicitante.id).subquery()

    # Definimos una “clave de persona” que será el email si existe, o el documento en su lugar
    grupo_persona = func.coalesce(Solicitante.emails, Solicitante.documento).label('grupo')

    # 1) Agrupamos por esa clave y contamos solicitudes > 1
    personas_multiples = (
       db.session.query(
        grupo_persona,
        func.count(Solicitante.id).label('cantidad')
        )
        .filter(Solicitante.id.in_(ids_filtrados))
        .group_by(grupo_persona)
        .having(func.count(Solicitante.id) > 1)
        .all()
    )

    # 2) Calculamos estadísticas simples
    if personas_multiples:
        total_personas = len(personas_multiples)
        total_apps    = sum(p.cantidad for p in personas_multiples)

        reaplicaciones_stats['total_personas_con_reaplicaciones'] = total_personas
        reaplicaciones_stats['total_reaplicaciones']             = total_apps
        reaplicaciones_stats['promedio_reaplicaciones']          = round(total_apps / total_personas, 1)
    
    return render_template('solicitantes/reportes.html',
        total_solicitantes=total_solicitantes,
        estadisticas_estado=estadisticas_estado,
        estadisticas_programa=estadisticas_programa,
        estadisticas_pais=estadisticas_pais,
        estadisticas_genero=estadisticas_genero,
        registros_mensuales=registros_mensuales,
        edad_stats=edad_stats,
        promedios_stats=promedios_stats,
        reaplicaciones_stats=reaplicaciones_stats,
        mesesNombres = mesesNombres,
        filtros={
            'fecha_inicio': fecha_inicio or '',
            'fecha_fin': fecha_fin or ''
        }
    )

@solicitantes_bp.route('/reportes/exportar', methods=['GET'])
@login_required
@require_role('Administrador', 'Director', 'Asistente', 'Consulta')
def exportar_reporte():
    from flask import Response
    import json
    from datetime import datetime, timedelta
    from sqlalchemy import func, extract
    
    # Aplicar los mismos filtros que en la ruta principal
    fecha_inicio = request.args.get('fecha_inicio')
    fecha_fin = request.args.get('fecha_fin')
    formato = request.args.get('formato', 'json')  # json o csv
    
    query = Solicitante.query
    
    if fecha_inicio:
        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
            query = query.filter(Solicitante.fecha_registro >= fecha_inicio_dt)
        except ValueError:
            pass
    
    if fecha_fin:
        try:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Solicitante.fecha_registro < fecha_fin_dt)
        except ValueError:
            pass
    
    # Recopilar todas las estadísticas
    total_solicitantes = query.count()
    
    estadisticas_estado = db.session.query(
        Solicitante.estado,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.estado).all()
    
    estadisticas_programa = db.session.query(
        Solicitante.programa_solicitado,
        func.count(Solicitante.id).label('cantidad')
    ).filter(Solicitante.id.in_(query.with_entities(Solicitante.id))).group_by(Solicitante.programa_solicitado).all()
    
    if formato == 'json':
        reporte = {
            'fecha_generacion': datetime.now().isoformat(),
            'filtros': {
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin
            },
            'total_solicitantes': total_solicitantes,
            'distribucion_por_estado': [
                {'estado': est.estado.value, 'cantidad': est.cantidad} for est in estadisticas_estado
            ],
            'distribucion_por_programa': [
                {'programa': prog.programa_solicitado.value, 'cantidad': prog.cantidad} for prog in estadisticas_programa
            ]
        }
        
        return Response(
            json.dumps(reporte, indent=2),
            mimetype='application/json',
            headers={"Content-Disposition": f"attachment;filename=reporte_solicitantes_{datetime.now().strftime('%Y%m%d_%H%M')}.json"}
        )
    
    else:  # CSV
        import csv
        from io import StringIO
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Escribir estadísticas por estado
        writer.writerow(['DISTRIBUCIÓN POR ESTADO'])
        writer.writerow(['Estado', 'Cantidad'])
        for est in estadisticas_estado:
            writer.writerow([est.estado.value, est.cantidad])
        
        writer.writerow([])  # Línea vacía
        
        # Escribir estadísticas por programa
        writer.writerow(['DISTRIBUCIÓN POR PROGRAMA'])
        writer.writerow(['Programa', 'Cantidad'])
        for prog in estadisticas_programa:
            writer.writerow([prog.programa_solicitado.value, prog.cantidad])
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": f"attachment;filename=reporte_solicitantes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"}
        )