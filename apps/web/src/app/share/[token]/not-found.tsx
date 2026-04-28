export default function ShareNotFound() {
  return (
    <main className="mx-auto max-w-md px-4 py-16 text-center" data-testid="share-not-found">
      <h1 className="text-2xl font-semibold">Link unavailable</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This shared chat has expired, been revoked, or never existed.
      </p>
    </main>
  );
}
