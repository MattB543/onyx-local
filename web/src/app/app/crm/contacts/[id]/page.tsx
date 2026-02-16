import CrmContactDetailPage from "@/refresh-pages/CrmContactDetailPage";

interface ContactDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function ContactDetailPage(props: ContactDetailPageProps) {
  const params = await props.params;
  return <CrmContactDetailPage contactId={params.id} />;
}

