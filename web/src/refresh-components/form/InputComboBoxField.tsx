"use client";

import { useField } from "formik";
import type { ChangeEvent, FocusEvent } from "react";

import {
  useOnBlurEvent,
  useOnChangeEvent,
  useOnChangeValue,
} from "@/hooks/formHooks";
import InputComboBox, {
  InputComboBoxProps,
} from "@/refresh-components/inputs/InputComboBox";

export interface InputComboBoxFieldProps extends Omit<
  InputComboBoxProps,
  "value" | "onChange" | "onValueChange" | "isError"
> {
  name: string;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  onValueChange?: (value: string) => void;
  onBlur?: (event: FocusEvent<HTMLInputElement>) => void;
}

export default function InputComboBoxField({
  name,
  onChange: onChangeProp,
  onValueChange: onValueChangeProp,
  onBlur: onBlurProp,
  ...inputProps
}: InputComboBoxFieldProps) {
  const [field, meta] = useField<string>(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const onValueChange = useOnChangeValue(name, onValueChangeProp);
  const onBlur = useOnBlurEvent(name, onBlurProp);
  const hasError = !!(meta.touched && meta.error);

  return (
    <InputComboBox
      {...inputProps}
      id={name}
      name={name}
      value={field.value ?? ""}
      onChange={onChange}
      onValueChange={onValueChange}
      onBlur={onBlur}
      isError={hasError}
    />
  );
}
