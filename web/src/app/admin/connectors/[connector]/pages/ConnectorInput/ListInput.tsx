import React from "react";
import { TextArrayField } from "@/components/Field";
import { useFormikContext } from "formik";

interface ListInputProps {
  name: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  label: string | ((credential: any) => string);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  description: string | ((credential: any) => string);
}

const ListInput: React.FC<ListInputProps> = ({ name, label, description }) => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { values } = useFormikContext<any>();
  return (
    <TextArrayField
      name={name}
      label={typeof label === "function" ? label(null) : label}
      values={values}
      subtext={
        typeof description === "function" ? description(null) : description
      }
      placeholder={`Enter ${
        typeof label === "function" ? label(null) : label.toLowerCase()
      }`}
    />
  );
};

export default ListInput;
