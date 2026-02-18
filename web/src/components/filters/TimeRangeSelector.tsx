import { DefaultDropdownElement } from "../Dropdown";

export function TimeRangeSelector({
  value,
  onValueChange,
  className,
  timeRangeValues,
}: {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  value: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onValueChange: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  className: any;

  timeRangeValues: { label: string; value: Date }[];
}) {
  return (
    <div className={className}>
      {timeRangeValues.map((timeRangeValue) => (
        <DefaultDropdownElement
          key={timeRangeValue.label}
          name={timeRangeValue.label}
          onSelect={() =>
            onValueChange({
              to: new Date(),
              from: timeRangeValue.value,
              selectValue: timeRangeValue.label,
            })
          }
          isSelected={value?.selectValue === timeRangeValue.label}
        />
      ))}
    </div>
  );
}
