from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.models.user import User


class UserForm(FlaskForm):
    nombre = StringField('Nombre', validators=[DataRequired(), Length(max=100)])
    email = StringField('Correo Electrónico', validators=[DataRequired(), Email(check_deliverability=False), Length(max=120)])
    rol = SelectField('Rol', choices=[('Administrador','Administrador'), ('Director','Director'), ('Asistente','Asistente'), ('Consulta','Consulta')], validators=[DataRequired()])
    password = PasswordField('Contraseña', validators=[Length(min=8, message='Mínimo 8 caracteres'), EqualTo('confirm_password', message='Las contraseñas deben coincidir')])
    confirm_password = PasswordField('Confirmar Contraseña')
    activo = BooleanField('Activo')
    submit = SubmitField('Guardar')

    def __init__(self, *args, **kwargs):
        # Capturar el objeto original antes de llamar al constructor padre
        self.original_user = kwargs.get('obj', None)
        super(UserForm, self).__init__(*args, **kwargs)
        
        # Asegurar que _obj esté disponible
        if self.original_user and not hasattr(self, '_obj'):
            self._obj = self.original_user

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        
        # Usar múltiples formas de obtener el usuario original para mayor robustez
        original_user = None
        if hasattr(self, '_obj') and self._obj:
            original_user = self._obj
        elif hasattr(self, 'original_user') and self.original_user:
            original_user = self.original_user
        
        # Validar solo si hay un usuario con este email y no es el usuario actual
        if user and (not original_user or user.id != getattr(original_user, 'id', None)):
            raise ValidationError('Este correo ya está en uso.')

class PasswordResetForm(FlaskForm):
    password = PasswordField('Nueva Contraseña', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password', message='Las contraseñas deben coincidir')])
    submit = SubmitField('Restablecer')