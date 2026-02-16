import CrmOrganizationDetailPage from "@/refresh-pages/CrmOrganizationDetailPage";

interface OrganizationDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function OrganizationDetailPage(
  props: OrganizationDetailPageProps
) {
  const params = await props.params;
  return <CrmOrganizationDetailPage organizationId={params.id} />;
}

