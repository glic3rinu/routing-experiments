import igraph
import logging
import random
import xml.etree.ElementTree as ET
import urllib.request
from heapq import heappop, heappush
from datetime import timedelta as delta

# TODO:
# - Get max distance

class NetworkGraph(igraph.Graph):
    @classmethod
    def from_cnml(cls, area):
        """
        Imports a Guifi.net area into networkx format. Only working nodes and 
        working links are considered. Results in an undirected graph.
        
        Keyword argument:
        area -- string that refers to the CNML area
        """
        url = 'http://guifi.net/en/guifi/cnml/%s/detail' % area
        response = urllib.request.urlopen(url)
        tree = ET.parse(response)
        gr = NetworkGraph()
        nodes = list(tree.getroot().findall(".//node[@status='Working']"))
        # Add every node in the graph
        for node in nodes:
            gr.add_vertex(node.get('id'),lon=node.get('lon'), lat=node.get('lat'))
        # Add every link within the graph
        for node in nodes:
            interfaces = node.findall('.//interface')
            src = node.get('id')
            for interface in interfaces:
                if interface.get('ipv4').startswith('172'):
                    links = interface.findall(".//link[@link_status='Working']")
                    for link in links:
                        dst = link.get('linked_node_id')
                        # Only add the link once and if the destination is in 
                        # the graph
                        if dst in gr.vs['name'] and src < dst:
                            gr.add_edge(src, dst)
        # Return only the biggest component
        return gr.clusters().giant()
    
    def random_link_changes(self, time_wait, time_off, duration, simultaneous=True):
        class Link:
            def __init__(self, src, dst, quality):
                self.src = src
                self.dst = dst
                self.quality = quality
            
            def __init__(self, link):
                self.link = link
                self.src = link.source
                self.dst = link.target
                self.quality = link['quality']
            
            def delete(self):
                self.link.delete()
            
            def __str__(self):
                return '(%s,%s,%s)' % (self.src, self.dst, self.quality)
        
        # We only consider links that won't partition the graph
        time = time_wait() if callable(time_wait) else time_wait
        changes = []
        graph = self.copy()
        links = list(set(graph.es).difference(graph.bridges()))
        off_links = []
        while time < duration:
            # Randomly choose a link
            off = time_off()+time if callable(time_off) else time_off+time
            next = time_wait() if callable(time_wait) else time_wait
            if links:
                link = Link(random.choice(links))
                changes.append((time, link, 0))
                # And disable it
                heappush(off_links, (off,link))
                link.delete()
            time = next+time if simultaneous else next+off
            # Enable links that should be on again
            while off_links and off_links[0][0] < time:
                (on_time,link) = heappop(off_links)
                if on_time < duration:
                    changes.append((on_time, link, link.quality))
                    graph.add_edge(link.src, link.dst, quality=link.quality)
            if simultaneous:
                links = list(set(graph.es).difference(graph.bridges()))
        # Set graph 'link_changes' = timedelta, src, dst, quality
        self['link_changes'] = []
        current = 0
        for (time, link, quality) in changes:
            change = (delta(seconds=time-current), link.src, link.dst, quality)
            self['link_changes'].append(change)
            current = time
    
    def bridges(self):
        def number_tree(tree, current, num=-1):
            if current['num'] is None:
                num += 1
                current['num'] = num
                for n in current.successors():
                    num = number_tree(tree, n, num)
            return num
        
        def _bridges_rec(tree, graph, node):
            node['visited'] = True
            lower = node['num']
            higher = node['num']
            descendants = 1
            bridges = []
            for neighbor in node.successors():
                if not neighbor['visited']:
                    bridges.extend(_bridges_rec(tree, graph, neighbor))
                    if neighbor['lower'] < lower:
                        lower = neighbor['lower']
                    if neighbor['higher'] > higher:
                        higher = neighbor['higher']
                    if (neighbor['lower'] == neighbor['num'] and
                            neighbor['higher'] < neighbor['num']+neighbor['descendants']):
                        edge = graph.get_eid(node.index,neighbor.index)
                        bridges.append(graph.es[edge])
                    descendants += neighbor['descendants']
            n_graph = [n.index for n in graph.vs[node.index].successors()]
            n_tree = [n.index for n in node.successors()]
            others =  set(n_graph).difference(n_tree)
            for o in others:
                reachable = tree.vs[o]['num']
                if reachable < lower:
                    lower = reachable
                if reachable > higher:
                    higher = reachable
            node['lower'] = lower
            node['higher'] = higher
            node['descendants'] = descendants
            return bridges
        
        # Get a spanning tree of the graph:
        tree = self.spanning_tree()
        # Transverse in pre-order and number the nodes:
        tree.vs['num'] = None
        number_tree(tree, tree.vs[0])
        # Compute recursively bridges:
        tree.vs['visited'] = False
        return _bridges_rec(tree, self, tree.vs[0])
    
    def set_quality(self, quality=3, edges=None):
        if edges is None:
            edges = self.es
        for edge in edges:
            edge['quality'] = quality() if callable(quality) else quality
    
    def save(self, filename, format='graphml'):
        # Save link_changes
        if format != 'pickle':
            try:
                changes = self['link_changes']
                with open('%s_changes' % filename, 'w') as f:
                    for ( time, src, dst, q ) in changes:
                        f.write('%f %i %i %i\n' % (time.total_seconds(), src, dst, q))
            except KeyError:
                pass
        logging.info(self)
        logging.info(filename)
        logging.info(format)
        super(NetworkGraph, self).save(filename, format)
    
    def get_longest_path(self):
        paths = self.shortest_paths_dijkstra()
        max_d = 0
        max_src = None
        max_dst = None
        for (src, distances) in enumerate(paths):
            for (dst, distance) in enumerate(distances):
                if distance > max_d:
                    max_d = distance
                    max_src = src
                    max_dst = dst
        return (max_src, max_dst)
