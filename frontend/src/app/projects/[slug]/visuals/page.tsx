import { redirect } from "next/navigation";

type Props = {
  params: Promise<{ slug: string }>;
};

/**
 * The Generate Visuals wizard now lives inline in the project workspace's
 * Visuals tab. This route just redirects back to the project page.
 */
export default async function VisualsPage({ params }: Props) {
  const { slug } = await params;
  redirect(`/projects/${slug}`);
}
