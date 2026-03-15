"use client";

import Text from "@/refresh-components/texts/Text";

export default function LoginText({
  brandName,
  isWhitelabeled,
}: {
  brandName: string;
  isWhitelabeled: boolean;
}) {
  return (
    <div className="w-full flex flex-col ">
      <Text as="p" headingH2 text05>
        Welcome to {brandName}
      </Text>
      {!isWhitelabeled && (
        <Text as="p" text03 mainUiMuted>
          Your open source AI platform for work
        </Text>
      )}
    </div>
  );
}
