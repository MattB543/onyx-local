import "server-only";

export function getServerAuthBranding() {
  const whitelabelName = process.env.WHITELABEL_NAME?.trim();

  if (whitelabelName) {
    return {
      brandName: whitelabelName,
      isWhitelabeled: true,
    };
  }

  return {
    brandName: "Onyx",
    isWhitelabeled: false,
  };
}
