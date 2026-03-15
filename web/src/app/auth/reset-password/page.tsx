import { redirect } from "next/navigation";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import ResetPasswordContent from "./ResetPasswordContent";

export default function Page() {
  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer>
      <ResetPasswordContent />
    </AuthFlowContainer>
  );
}
