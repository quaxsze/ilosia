from django import forms
from django.core.validators import MaxValueValidator, MinValueValidator

from .models import environment_name_validator, service_name_validator

RESERVED_VARIABLES = {
    "JUPYTER_TOKEN",
    "S3_ACCESS_KEY",
    "S3_BUCKET",
    "S3_ENDPOINT",
    "S3_SECRET_KEY",
}


class LaunchServiceForm(forms.Form):
    display_name = forms.CharField(
        label="Name",
        min_length=1,
        max_length=63,
        validators=[service_name_validator],
    )
    cpu_units = forms.IntegerField(label="CPU")
    memory_gib = forms.IntegerField(label="Memory (GiB)")
    storage_gib = forms.IntegerField(label="Storage (GiB)")
    environment_variables = forms.CharField(
        label="Environment variables",
        required=False,
        max_length=32768,
        widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        help_text="One NAME=value entry per line.",
    )
    secret_variables = forms.CharField(
        label="Secret variables",
        required=False,
        max_length=32768,
        widget=forms.Textarea(
            attrs={"rows": 4, "spellcheck": "false", "autocomplete": "off"}
        ),
        help_text="One NAME=value entry per line. Values are not stored in Django.",
    )

    def __init__(self, *args, definition, **kwargs):
        super().__init__(*args, **kwargs)
        self.definition = definition

        self.fields["display_name"].initial = f"my-{definition.slug}"
        self._configure_number_field(
            "cpu_units",
            definition.default_cpu_units,
            definition.min_cpu_units,
            definition.max_cpu_units,
        )
        self._configure_number_field(
            "memory_gib",
            definition.default_memory_mib // 1024,
            definition.min_memory_mib // 1024,
            definition.max_memory_mib // 1024,
        )
        self._configure_number_field(
            "storage_gib",
            definition.default_storage_mib // 1024,
            definition.min_storage_mib // 1024,
            definition.max_storage_mib // 1024,
        )

        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def _configure_number_field(self, name, initial, minimum, maximum):
        field = self.fields[name]
        field.initial = initial
        field.min_value = minimum
        field.max_value = maximum
        field.validators.extend(
            [MinValueValidator(minimum), MaxValueValidator(maximum)]
        )
        field.widget.attrs.update({"min": minimum, "max": maximum, "step": 1})
        field.help_text = f"Allowed range: {minimum}–{maximum}."

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"].strip()
        if not display_name:
            raise forms.ValidationError("Enter a name.")
        return display_name

    def clean_environment_variables(self):
        return self._parse_variables("environment_variables")

    def clean_secret_variables(self):
        return self._parse_variables("secret_variables")

    def clean(self):
        cleaned_data = super().clean()
        variables = cleaned_data.get("environment_variables", {})
        secrets = cleaned_data.get("secret_variables", {})
        duplicates = variables.keys() & secrets.keys()
        if duplicates:
            raise forms.ValidationError(
                f"Variables cannot be both regular and secret: {', '.join(sorted(duplicates))}."
            )
        if len(variables) + len(secrets) > 50:
            raise forms.ValidationError("A service can have at most 50 variables.")
        return cleaned_data

    def _parse_variables(self, field_name):
        result = {}
        for line_number, line in enumerate(
            self.cleaned_data[field_name].splitlines(), start=1
        ):
            if not line.strip():
                continue
            name, separator, value = line.partition("=")
            name = name.strip()
            if not separator:
                raise forms.ValidationError(f"Line {line_number} must use NAME=value.")
            try:
                environment_name_validator(name)
            except forms.ValidationError as error:
                raise forms.ValidationError(
                    f"Line {line_number}: {error.messages[0]}"
                ) from error
            if name in RESERVED_VARIABLES:
                raise forms.ValidationError(f"{name} is reserved.")
            if name in result:
                raise forms.ValidationError(f"Variable {name} is duplicated.")
            result[name] = value
        return result
