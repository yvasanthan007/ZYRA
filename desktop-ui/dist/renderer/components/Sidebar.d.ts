import React from 'react';
type View = 'chat' | 'commands' | 'monitor' | 'settings';
interface SidebarProps {
    activeView: View;
    onViewChange: (view: View) => void;
}
declare const Sidebar: React.FC<SidebarProps>;
export default Sidebar;
//# sourceMappingURL=Sidebar.d.ts.map