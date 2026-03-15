import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import ErrorContent from "./ErrorContent";

export default function Page() {
  return (
    <AuthFlowContainer>
      <ErrorContent />
    </AuthFlowContainer>
  );
}
