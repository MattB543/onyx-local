import { useMemo } from "react";
import { defaultTailwindCSS, IconProps } from "@/components/icons/icons";
import { getProviderIcon } from "@/app/admin/configuration/llm/utils";

export interface ProviderIconProps extends IconProps {
  provider: string;
  modelName?: string;
}

export const ProviderIcon = ({
  provider,
  modelName,
  size = 16,
  className = defaultTailwindCSS,
}: ProviderIconProps) => {
  const Icon = useMemo(() => getProviderIcon(provider, modelName), [provider, modelName]);
  // eslint-disable-next-line react-hooks/static-components -- dynamic icon component selected by provider
  return <Icon size={size} className={className} />;
};
