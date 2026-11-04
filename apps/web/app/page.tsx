import { Suspense } from "react";
import Catalogue from "./catalogue";

export default function Page() {
  return (
    <Suspense>
      <Catalogue />
    </Suspense>
  );
}
