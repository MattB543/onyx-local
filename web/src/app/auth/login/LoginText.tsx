"use client";

import React, { useContext } from "react";
import { SettingsContext } from "@/providers/SettingsProvider";
import Text from "@/refresh-components/texts/Text";
import { NEXT_PUBLIC_WHITELABEL_NAME } from "@/lib/constants";

export default function LoginText() {
  const settings = useContext(SettingsContext);
  const displayName =
    NEXT_PUBLIC_WHITELABEL_NAME ||
    (settings && settings?.enterpriseSettings?.application_name) ||
    "Onyx";
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        Welcome to {displayName}
      </Text>
      {!NEXT_PUBLIC_WHITELABEL_NAME && (
        <Text as="p" text03 mainUiMuted>
          Your open source AI platform for work
        </Text>
      )}
    </div>
  );
}
