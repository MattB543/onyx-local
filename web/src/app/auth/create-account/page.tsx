import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { getServerAuthBranding } from "@/lib/serverBranding";
import CreateAccountContent from "./CreateAccountContent";

export default function Page() {
  const { brandName } = getServerAuthBranding();

  return (
    <AuthFlowContainer>
      <CreateAccountContent brandName={brandName} />
    </AuthFlowContainer>
  );
}
