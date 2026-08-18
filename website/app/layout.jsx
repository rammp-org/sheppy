import { Footer, Layout, Navbar } from 'nextra-theme-docs'
import { Head } from 'nextra/components'
import { getPageMap } from 'nextra/page-map'
import 'nextra-theme-docs/style.css'

export const metadata = {
  title: { default: 'Sheppy', template: '%s – Sheppy' },
  description: 'Sheppy herds the ROS2 nodes of a distributed robotics project.'
}

const navbar = (
  <Navbar
    logo={<span style={{ fontWeight: 700 }}>🐑🐕 Sheppy</span>}
    projectLink="https://github.com/rammp-org/sheppy"
  />
)

const footer = <Footer>MIT {new Date().getFullYear()} © Sheppy.</Footer>

export default async function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <Head />
      <body>
        <Layout
          navbar={navbar}
          pageMap={await getPageMap()}
          docsRepositoryBase="https://github.com/rammp-org/sheppy/tree/main/website"
          footer={footer}
          editLink="Edit this page on GitHub"
          sidebar={{ defaultMenuCollapseLevel: 2 }}
        >
          {children}
        </Layout>
      </body>
    </html>
  )
}
