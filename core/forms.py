from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser

NEO_INPUT_CLASS = (
    'w-full px-4 py-3 rounded-xl border-[2.5px] border-[#111827] bg-white '
    'text-[#111827] font-bold placeholder-gray-400 focus:outline-none '
    'focus:ring-2 focus:ring-[#38BDF8] shadow-[3px_3px_0px_#111827] transition'
)


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': 'Ismingiz'}),
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': 'Familiyangiz'}),
    )
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': '+998 90 123 45 67'}),
    )
    age = forms.IntegerField(
        required=False,
        initial=18,
        widget=forms.NumberInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': 'Yoshingiz', 'min': '5', 'max': '120'}),
    )
    preferred_language = forms.ChoiceField(
        choices=CustomUser.LANGUAGE_CHOICES,
        required=True,
        initial='uz',
        widget=forms.Select(attrs={'class': NEO_INPUT_CLASS}),
    )

    class Meta:
        model = CustomUser
        fields = (
            'username', 'first_name', 'last_name',
            'phone_number', 'age', 'preferred_language',
            'password1', 'password2',
        )
        widgets = {
            'username': forms.TextInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': 'username'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({'class': NEO_INPUT_CLASS, 'placeholder': 'Parol'})
        self.fields['password2'].widget.attrs.update({'class': NEO_INPUT_CLASS, 'placeholder': 'Parolni tasdiqlang'})


class CustomAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': 'username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': NEO_INPUT_CLASS, 'placeholder': '••••••••'})
    )
