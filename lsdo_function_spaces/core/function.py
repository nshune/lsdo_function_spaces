from __future__ import annotations

from dataclasses import dataclass
import csdl_alpha as csdl
import numpy as np


from lsdo_function_spaces.core.function_space import FunctionSpace



@dataclass
class Function:
    '''
    Function class. This class is used to represent a function in a given function space. The function space is used to evaluate the function at
    given coordinates, refit the function, and project points onto the function.

    Attributes
    ----------
    space : FunctionSpace
        The function space in which the function resides.
    coefficients : csdl.Variable -- shape=coefficients_shape or (num_coefficients,)
        The coefficients of the function.
    '''
    space: FunctionSpace
    coefficients: csdl.Variable

    def __post_init__(self):
        pass

    def evaluate(self, parametric_coordinates:np.ndarray, parametric_derivative_order:tuple=None, coefficients:csdl.Variable=None,
                 plot:bool=False) -> csdl.Variable:
        '''
        Evaluates the function.

        Parameters
        ----------
        parametric_coordinates : np.ndarray -- shape=(num_points, num_parametric_dimensions)
            The coordinates at which to evaluate the function.
        parametric_derivative_order : tuple = None -- shape=(num_points,num_parametric_dimensions)
            The order of the parametric derivatives to evaluate.
        coefficients : csdl.Variable = None -- shape=coefficients_shape or (num_coefficients,)
            The coefficients of the function.
        plot : bool = False
            Whether or not to plot the function with the points from the result of the evaluation.
        

        Returns
        -------
        function_values : csdl.Variable
            The function evaluated at the given coordinates.
        '''
        if coefficients is None:
            coefficients = self.coefficients

        function_values = self.space.evaluate(
            coefficients=coefficients,
            parametric_coordinates=parametric_coordinates,
            parametric_derivative_order=parametric_derivative_order,
            plot=plot)

        return function_values
    

    def refit(self, new_function_space:FunctionSpace, grid_resolution:tuple=None, 
              parametric_coordinates:np.ndarray=None, parametric_derivative_orders:np.ndarray=None,
              regularization_parameter:float=None) -> Function:
        '''
        Optimally refits the function. Either a grid resolution or parametric coordinates must be provided. 
        If both are provided, the parametric coordinates will be used. If derivatives are used, the parametric derivative orders must be provided.

        NOTE: this method will not overwrite the coefficients or function space in this object. 
        It will return a new function object with the refitted coefficients.

        Parameters
        ----------
        new_function_space : FunctionSpace
            The new function space that the function will be picked from.
        grid_resolution : tuple = None -- shape=(num_parametric_dimensions,)
            The resolution of the grid to refit the function.
        parametric_coordinates : np.ndarray = None -- shape=(num_points, num_parametric_dimensions)
            The coordinates at which to refit the function.
        parametric_derivative_orders : np.ndarray = None -- shape=(num_points, num_parametric_dimensions)
            The orders of the parametric derivatives to refit.

        Returns
        -------
        Function
            The refitted function with the new function space and new coefficients.
        '''

        '''
        NOTE: TODO: Look at error in L2 sense and think about whether this actually minimizes the error!!
        Additional NOTE: When the order changes, the ideal parametric coordinate corresponding to a value seems like it might change.
        -- To clarify: A point that is at u=0.1 in one function space may actually ideally be at u=0.15 or whatever in another function space.
        '''
        if parametric_coordinates is None and grid_resolution is None:
            # raise ValueError("Either grid resolution or parametric coordinates must be provided.")
            grid_resolution = (100,)*self.space.num_parametric_dimensions
        if parametric_coordinates is not None and grid_resolution is not None:
            print("Warning: Both grid resolution and parametric coordinates were provided. Using parametric coordinates.")
            # raise Warning("Both grid resolution and parametric coordinates were provided. Using parametric coordinates.")
        
        if parametric_coordinates is None:
            # if grid_resolution is not None: # Don't need this line because we already error checked at the beginning.
            mesh_grid_input = []
            for dimension_index in range(self.space.num_parametric_dimensions):
                mesh_grid_input.append(np.linspace(0., 1., grid_resolution[dimension_index]))

            parametric_coordinates_tuple = np.meshgrid(*mesh_grid_input, indexing='ij')
            for dimensions_index in range(self.space.num_parametric_dimensions):
                parametric_coordinates_tuple[dimensions_index] = parametric_coordinates_tuple[dimensions_index].reshape((-1,1))

            parametric_coordinates = np.hstack(parametric_coordinates_tuple)

        basis_matrix = self.space.compute_basis_matrix(parametric_coordinates, parametric_derivative_orders)
        coefficients_reshaped = self.coefficients.reshape((self.coefficients.size//self.coefficients.shape[-1],  self.coefficients.shape[-1]))
        fitting_values = csdl.Variable(value=np.zeros((parametric_coordinates.shape[0], self.coefficients.shape[-1])))
        for i in range(self.coefficients.shape[-1]):
            fitting_values = fitting_values.set(csdl.slice[:,i], csdl.sparse.matvec(basis_matrix, 
                                                                                    coefficients_reshaped[:,i].reshape((coefficients_reshaped.shape[0],1))).flatten())
        # fitting_values = basis_matrix.dot(self.coefficients.value.reshape((-1,self.coefficients.shape[-1])))
        
        coefficients = new_function_space.fit(
            values=fitting_values,
            parametric_coordinates=parametric_coordinates,
            parametric_derivative_orders=parametric_derivative_orders,
            regularization_parameter=regularization_parameter)
        
        new_function = Function(space=new_function_space, coefficients=coefficients)
        return new_function


    def project(self, points:np.ndarray, direction:np.ndarray=None, grid_search_density_parameter:int=1, 
                max_newton_iterations:int=100, newton_tolerance:float=1e-6, plot:bool=False) -> csdl.Variable:
        '''
        Projects a set of points onto the function. The points to project must be provided. If a direction is provided, the projection will find
        the points on the function that are closest to the axis defined by the direction. If no direction is provided, the projection will find the
        points on the function that are closest to the points to project. The grid search density parameter controls the density of the grid search
        used to find the initial guess for the Newton iterations. The max newton iterations and newton tolerance control the convergence of the
        Newton iterations. If plot is True, a plot of the projection will be displayed.

        NOTE: Distance is measured by the 2-norm.

        Parameters
        ----------
        points : np.ndarray -- shape=(num_points, num_phyiscal_dimensions)
            The points to project onto the function.
        direction : np.ndarray = None -- shape=(num_parametric_dimensions,)
            The direction of the projection.
        grid_search_density_parameter : int = 1
            The density of the grid search used to find the initial guess for the Newton iterations.
        max_newton_iterations : int = 100
            The maximum number of Newton iterations.
        newton_tolerance : float = 1e-6
            The tolerance for the Newton iterations.
        plot : bool = False
            Whether or not to plot the projection.
        '''
        num_physical_dimensions = points.shape[-1]

        grid_search_resolution = 100*grid_search_density_parameter//self.space.num_parametric_dimensions + 1

        # Perform a grid search
        if direction is None:
            # If no direction is provided, the projection will find the points on the function that are closest to the points to project.
            # The grid search will be used to find the initial guess for the Newton iterations
            
            # Generate parametric grid
            mesh_grid_input = []
            for dimension_index in range(self.space.num_parametric_dimensions):
                mesh_grid_input.append(np.linspace(0., 1., grid_search_resolution))

            parametric_coordinates_tuple = np.meshgrid(*mesh_grid_input, indexing='ij')
            for dimensions_index in range(self.space.num_parametric_dimensions):
                parametric_coordinates_tuple[dimensions_index] = parametric_coordinates_tuple[dimensions_index].reshape((-1,1))

            parametric_grid_search = np.hstack(parametric_coordinates_tuple)

            # Evaluate grid of points
            function_values = self.evaluate(parametric_grid_search).value

            # Find closest point on function to each point to project
            # closest_point_indices = np.argmin(np.linalg.norm(function_values - points, axis=1))
            points_expanded = np.repeat(points[:,np.newaxis,:], function_values.shape[0], axis=1)
            grid_search_distances = np.linalg.norm(points_expanded - function_values, axis=2)
            closest_point_indices = np.argmin(grid_search_distances, axis=1)

            # Use the parametric coordinate corresponding to each closest point as the initial guess for the Newton iterations
            initial_guess = parametric_grid_search[closest_point_indices]
        else:
            # If a direction is provided, the projection will find the points on the function that are closest to the axis defined by the direction.
            # The grid search will be used to find the initial guess for the Newton iterations
            grid_search_points = points + np.outer(np.linspace(-1., 1., grid_search_density_parameter), direction)


        current_guess = initial_guess.copy()
        # As a first implementation approach, loop over points to project and perform Newton optimization for each point
        for i in range(points.shape[0]):
            for j in range(max_newton_iterations):
                # Perform B-spline evaluations needed for gradient and hessian (0th, 1st, and 2nd order derivatives needed)
                function_value = self.evaluate(current_guess[i]).value

                displacement = (points[i] - function_value).flatten()
                d_displacement_d_parametric = np.zeros((num_physical_dimensions, self.space.num_parametric_dimensions,))
                d2_displacement_d_parametric2 = np.zeros((num_physical_dimensions, self.space.num_parametric_dimensions, self.space.num_parametric_dimensions))
                for k in range(self.space.num_parametric_dimensions):
                    parametric_derivative_orders = np.zeros((self.space.num_parametric_dimensions,), dtype=int)
                    parametric_derivative_orders[k] = 1
                    d_displacement_d_parametric[:,k] = -self.space.compute_basis_matrix(
                        current_guess[i], parametric_derivative_orders=parametric_derivative_orders
                        ).dot(self.coefficients.value.reshape((-1,num_physical_dimensions)))
                    for m in range(self.space.num_parametric_dimensions):
                        parametric_derivative_orders = np.zeros((self.space.num_parametric_dimensions,))
                        if m == k:
                            parametric_derivative_orders[m] = 2
                        else:
                            parametric_derivative_orders[k] = 1
                            parametric_derivative_orders[m] = 1
                        d2_displacement_d_parametric2[:,k,m] = -self.space.compute_basis_matrix(
                            current_guess[i], parametric_derivative_orders=parametric_derivative_orders
                            ).dot(self.coefficients.value.reshape((-1,num_physical_dimensions)))

                # Construct the gradient and hessian
                gradient = 2*displacement.dot(d_displacement_d_parametric)
                hessian = 2*(np.tensordot(d_displacement_d_parametric, d_displacement_d_parametric, axes=[0,0])
                             + np.tensordot(displacement, d2_displacement_d_parametric2, axes=[0,0]))
                
                # Remove dof that are on constrant boundary and want to leave (active subspace method)
                coorinates_to_remove_on_lower_boundary = np.logical_and(current_guess[i] == 0, gradient > 0)
                coorinates_to_remove_on_upper_boundary = np.logical_and(current_guess[i] == 1, gradient < 0)
                coorinates_to_remove = np.logical_or(coorinates_to_remove_on_lower_boundary, coorinates_to_remove_on_upper_boundary)
                coordinates_to_keep = np.arange(self.space.num_parametric_dimensions)[np.logical_not(coorinates_to_remove)]

                # coordinates_to_keep = np.setdiff1d(np.arange(self.space.num_parametric_dimensions), coorinates_to_remove)
                reduced_gradient = gradient[coordinates_to_keep]
                reduced_hessian = hessian[np.ix_(coordinates_to_keep, coordinates_to_keep)]
                
                # # Finite difference check gradient
                # finite_difference_gradient = np.zeros((self.space.num_parametric_dimensions,))
                # for k in range(self.space.num_parametric_dimensions):
                #     delta = 1e-6
                #     current_guess_plus_delta = current_guess[i].copy()
                #     current_guess_plus_delta[k] += delta
                #     function_value_plus_delta = self.evaluate(current_guess_plus_delta).value
                #     displacement_plus_delta = (points[i] - function_value_plus_delta).flatten()
                #     objective = displacement_plus_delta.dot(displacement_plus_delta)
                #     finite_difference_gradient[k] = (objective - displacement.dot(displacement))/delta

                # Check for convergence
                if np.linalg.norm(reduced_gradient) < newton_tolerance:
                    break

                # Solve the linear system
                # delta = np.linalg.solve(hessian, -gradient)
                delta = np.linalg.solve(reduced_hessian, -reduced_gradient)

                # Update the initial guess
                current_guess[i,coordinates_to_keep] += delta
                # If any of the coordinates are outside the bounds, set them to the bounds
                current_guess[i] = np.clip(current_guess[i], 0., 1.)

        # # Experimental implementation that does all the Newton optimizations at once to vectorize many of the computations
        # current_guess = initial_guess.copy()
        # points_left_to_converge = np.arange(points.shape[0])
        # for j in range(max_newton_iterations):
        #     # Perform B-spline evaluations needed for gradient and hessian (0th, 1st, and 2nd order derivatives needed)
        #     function_values = self.evaluate(current_guess[points_left_to_converge]).value
        #     displacements = (points[points_left_to_converge] - function_values).reshape(points_left_to_converge.shape[0], num_physical_dimensions)
            
        #     d_displacement_d_parametric = np.zeros((points_left_to_converge.shape[0], num_physical_dimensions, self.space.num_parametric_dimensions))
        #     d2_displacement_d_parametric2 = np.zeros((points_left_to_converge.shape[0], num_physical_dimensions, 
        #                                               self.space.num_parametric_dimensions, self.space.num_parametric_dimensions))

        #     for k in range(self.space.num_parametric_dimensions):
        #         parametric_derivative_orders = np.zeros((self.space.num_parametric_dimensions,), dtype=int)
        #         parametric_derivative_orders[k] = 1
        #         # d_displacement_d_parametric[:, :, k] = -np.tensordot(
        #         #     self.space.compute_basis_matrix(current_guess, parametric_derivative_orders=parametric_derivative_orders),
        #         #     self.coefficients.value.reshape(-1, num_physical_dimensions), axes=[1,0])
        #         d_displacement_d_parametric[:, :, k] = -self.space.compute_basis_matrix(current_guess[points_left_to_converge], 
        #                                                                                 parametric_derivative_orders=parametric_derivative_orders).dot(
        #                                                             self.coefficients.value.reshape(-1, num_physical_dimensions))
        #             # NOTE on indices: i=points, j=coefficients, k=physical dimensions

        #         for m in range(self.space.num_parametric_dimensions):
        #             parametric_derivative_orders = np.zeros((self.space.num_parametric_dimensions,))
        #             if m == k:
        #                 parametric_derivative_orders[m] = 2
        #             else:
        #                 parametric_derivative_orders[k] = 1
        #                 parametric_derivative_orders[m] = 1
        #             # d2_displacement_d_parametric2[:, :, k, m] = -np.einsum(
        #             #     self.space.compute_basis_matrix(current_guess, parametric_derivative_orders=parametric_derivative_orders),
        #             #     self.coefficients.value.reshape((-1, num_physical_dimensions)), 'ij,jk->ik')
        #             d2_displacement_d_parametric2[:, :, k, m] = -self.space.compute_basis_matrix(current_guess[points_left_to_converge], 
        #                                                                     parametric_derivative_orders=parametric_derivative_orders).dot(
        #                                                                 self.coefficients.value.reshape((-1, num_physical_dimensions)))
        #                 # NOTE on indices: i=points, j=coefficients, k=physical dimensions

        #     # Construct the gradient and hessian
        #     gradient = 2 * np.einsum('ij,ijk->ik', displacements, d_displacement_d_parametric)
        #     hessian = 2 * (np.einsum('ijk,ijm->ikm', d_displacement_d_parametric, d_displacement_d_parametric)
        #                 + np.einsum('ij,ijkm->ikm', displacements, d2_displacement_d_parametric2))

        #     # Remove dof that are on constrant boundary and want to leave (active subspace method)
        #     coorinates_to_remove_on_lower_boundary = np.logical_and(current_guess[points_left_to_converge] == 0, gradient > 0)
        #     coorinates_to_remove_on_upper_boundary = np.logical_and(current_guess[points_left_to_converge] == 1, gradient < 0)
        #     coorinates_to_remove_boolean = np.logical_or(coorinates_to_remove_on_lower_boundary, coorinates_to_remove_on_upper_boundary)
        #     coordinates_to_keep_boolean = np.logical_not(coorinates_to_remove_boolean)
        #     indices_to_keep = []
        #     for i in range(points_left_to_converge.shape[0]):
        #         indices_to_keep.append(np.arange(self.space.num_parametric_dimensions)[coordinates_to_keep_boolean[i]])

        #     reduced_gradients = []
        #     reduced_hessians = []
        #     total_gradient_norm = 0.
        #     counter = 0
        #     for i in range(points_left_to_converge.shape[0]):
        #         reduced_gradient = gradient[i, indices_to_keep[counter]]

        #         if np.linalg.norm(reduced_gradient) < newton_tolerance:
        #             points_left_to_converge = np.delete(points_left_to_converge, counter)
        #             del indices_to_keep[counter]
        #             continue

        #         # This is after check so it doesn't throw error
        #         reduced_hessian = hessian[np.ix_(np.array([i]), indices_to_keep[counter], indices_to_keep[counter])][0]    

        #         reduced_gradients.append(reduced_gradient)
        #         reduced_hessians.append(reduced_hessian)
        #         total_gradient_norm += np.linalg.norm(reduced_gradient)
        #         counter += 1

        #     # Check for convergence
        #     if np.linalg.norm(total_gradient_norm) < newton_tolerance:
        #         break

        #     # Solve the linear systems
        #     for i, index in enumerate(points_left_to_converge):
        #         delta = np.linalg.solve(reduced_hessians[i], -reduced_gradients[i])

        #         # Update the initial guess
        #         current_guess[index, indices_to_keep[i]] += delta

        #     # If any of the coordinates are outside the bounds, set them to the bounds
        #     current_guess[points_left_to_converge[i]] = np.clip(current_guess[points_left_to_converge[i]], 0., 1.)


        return current_guess




    def _check_whether_to_load_projection(self, points:np.ndarray, direction:np.ndarray=None, grid_search_density_parameter:int=1,
                                         max_newton_iterations:int=100, newton_tolerance:float=1e-6) -> bool:
        pass


    def plot(self, point_types:list=['evaluated_points'], plot_types:list=['surface'],
              opacity:float=1., color:str|Function='#00629B', color_map:str='jet', surface_texture:str="",
              line_width:float=3., additional_plotting_elements:list=[], show:bool=True) -> list:
        '''
        Plots the B-spline Surface.

        Parameters
        -----------
        points_type : list = ['evaluated_points']
            The type of points to be plotted. {evaluated_points, coefficients}
        plot_types : list = ['surface']
            The type of plot {surface, wireframe, point_cloud}
        opactity : float = 1.
            The opacity of the plot. 0 is fully transparent and 1 is fully opaque.
        color : str = '#00629B'
            The 6 digit color code to plot the B-spline as. If a function is provided, the function will be used to color the B-spline.
        surface_texture : str = "" {"metallic", "glossy", ...}, optional
            The surface texture to determine how light bounces off the surface.
            See https://github.com/marcomusy/vedo/blob/master/examples/basic/lightings.py for options.
        color_map : str = 'jet'
            The color map to use if the color is a function.
        additional_plotting_elemets : list
            Vedo plotting elements that may have been returned from previous plotting functions that should be plotted with this plot.
        show : bool
            A boolean on whether to show the plot or not. If the plot is not shown, the Vedo plotting element is returned.

        Returns
        -------
        plotting_elements : list
            The Vedo plotting elements that were plotted.
        '''
        for point_type in point_types:
            if point_type not in ['evaluated_points', 'coefficients']:
                raise ValueError("Invalid point type. Must be 'evaluated_points' or 'coefficients'.")
            
            if point_type == 'coefficients' and self.coefficients is None:
                raise ValueError("The coefficients of the function are not defined.")
            
            if self.space.num_parametric_dimensions == 1:
                # NOTE: Curve plotting not currently implemented for points in 3D space because I don't have a num_physical_dimensions attribute.
                return self.plot_curve(point_type=point_type, opacity=opacity, color=color, color_map=color_map,
                                       line_width=line_width, additional_plotting_elements=additional_plotting_elements, show=show)
            
            elif self.space.num_parametric_dimensions == 2:
                return self.plot_surface(point_type=point_type, plot_types=plot_types, opacity=opacity, color=color, color_map=color_map,
                                        surface_texture=surface_texture, line_width=line_width, additional_plotting_elements=additional_plotting_elements, show=show)
            elif self.space.num_parametric_dimensions == 3:
                return self.plot_volume(point_type=point_type, plot_types=plot_types, opacity=opacity, color=color, color_map=color_map,
                                        surface_texture=surface_texture, line_width=line_width, additional_plotting_elements=additional_plotting_elements, show=show)


    def plot_curve(self, point_type:str='evaluated_points', opacity:float=1., color:str|Function='#00629B', color_map:str='jet',
                   line_width:float=3., additional_plotting_elements:list=[], show:bool=True):
        '''
        Plots the function as a curve. NOTE: This should only be called if the function is a curve!

        Parameters
        -----------
        points_type : str = 'evaluated_points'
            The type of points to be plotted. {evaluated_points, coefficients}
        opactity : float = 1.
            The opacity of the plot. 0 is fully transparent and 1 is fully opaque.
        color : str = '#00629B'
            The 6 digit color code to plot the function as. If a function is provided, the function will be used to color the curve.
        color_map : str = 'jet'
            The color map to use if the color is a function.
        additional_plotting_elemets : list = []
            Vedo plotting elements that may have been returned from previous plotting functions that should be plotted with this plot.
        show : bool = True
            A boolean on whether to show the plot or not. If the plot is not shown, the Vedo plotting element is returned.

        Returns
        -------
        plotting_elements : list
            The Vedo plotting elements that were plotted.
        '''
        import lsdo_function_spaces.utils.plotting_functions as pf
        if self.space.num_parametric_dimensions != 1:
            raise ValueError("This function is not a curve and cannot be plotted as one.")
        
        # region Generate the points to plot
        if point_type == 'evaluated_points':
            num_points = 100
            parametric_coordinates = np.linspace(0., 1., num_points).reshape((-1,1))
            function_values = self.evaluate(parametric_coordinates).value

            # scale u axis to be more visually clear based on scaling of parameter
            u_axis_scaling = np.max(function_values) - np.min(function_values)
            if u_axis_scaling != 0:
                parametric_coordinates = parametric_coordinates * u_axis_scaling
            points = np.hstack((parametric_coordinates, function_values))

            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 1:
                    raise ValueError("The color function must be 1D to plot as a curve.")
                
                color = color.evaluate(parametric_coordinates).value
        elif point_type == 'coefficients':
            # NOTE: Check this line below!! I think this should really be the knot vector but I don't want to hardcode the existence of the knot vector.
            parametric_coordinates = np.linspace(0., 1., self.coefficients.shape[0]).reshape((-1,1))

            # scale u axis to be more visually clear based on scaling of parameter
            u_axis_scaling = np.max(self.coefficients.value) - np.min(self.coefficients.value)
            if u_axis_scaling != 0:
                parametric_coordinates = parametric_coordinates * u_axis_scaling

            points = np.hstack((parametric_coordinates, self.coefficients.value))

            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 1:
                    raise ValueError("The color function must be 1D to plot as a curve.")
                
                color = color.coefficients.value
                if color.size != points.size:
                    # If the number of coefficients are different, just evaluate the color function at the locations of the coefficients of the function.
                    color = color.evaluate(parametric_coordinates).value
        else:
            raise ValueError("Invalid point type. Must be 'evaluated_points' or 'coefficients'.")
        # endregion Generate the points to plot

        # Call general plot curve function to plot the points with the colors
        plotting_elements = pf.plot_curve(points=points, opacity=opacity, color=color, color_map=color_map, line_width=line_width, 
                                          additional_plotting_elements=additional_plotting_elements, show=show)
        return plotting_elements
    

    def plot_surface(self, point_type:str='evaluated_points', plot_types:list=['surface'], opacity:float=1., color:str|Function='#00629B',
                        color_map:str='jet', surface_texture:str="", line_width:float=3., additional_plotting_elements:list=[], show:bool=True):
        '''
        Plots the function as a surface. NOTE: This should only be called if the function is a surface!

        Parameters
        -----------
        points_type : str = 'evaluated_points'
            The type of points to be plotted. {evaluated_points, coefficients}
        plot_types : list = ['surface']
            The type of plot {surface, wireframe, point_cloud}
        opactity : float = 1.
            The opacity of the plot. 0 is fully transparent and 1 is fully opaque.
        color : str = '#00629B'
            The 6 digit color code to plot the function as. If a function is provided, the function will be used to color the surface.
        color_map : str = 'jet'
            The color map to use if the color is a function.
        surface_texture : str = ""
            The surface texture to determine how light bounces off the surface.
            See https://github.com/marcomusy/vedo/blob/master/examples/basic/lightings.py for options.
        line_width : float = 3.
            The width of the lines if the plot type is wireframe.
        additional_plotting_elemets : list = []
            Vedo plotting elements that may have been returned from previous plotting functions that should be plotted with this plot.
        show : bool = True
            A boolean on whether to show the plot or not. If the plot is not shown, the Vedo plotting element is returned.

        Returns
        -------
        plotting_elements : list
            The Vedo plotting elements that were plotted.
        '''
        import lsdo_function_spaces.utils.plotting_functions as pf
        if self.space.num_parametric_dimensions != 2:
            raise ValueError("This function is not a surface and cannot be plotted as one.")
        
        # region Generate the points to plot
        if point_type == 'evaluated_points':
            num_points = 25

            # Generate meshgrid of parametric coordinates
            mesh_grid_input = []
            for dimension_index in range(self.space.num_parametric_dimensions):
                mesh_grid_input.append(np.linspace(0., 1., num_points))
            parametric_coordinates_tuple = np.meshgrid(*mesh_grid_input, indexing='ij')
            for dimensions_index in range(self.space.num_parametric_dimensions):
                parametric_coordinates_tuple[dimensions_index] = parametric_coordinates_tuple[dimensions_index].reshape((-1,1))
            parametric_coordinates = np.hstack(parametric_coordinates_tuple)
            
            function_values = self.evaluate(parametric_coordinates).value.reshape((num_points,num_points,-1))
            points = function_values

            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 2:
                    raise ValueError("The color function must be 2D to plot as a surface.")
                
                color = color.evaluate(parametric_coordinates).value
        elif point_type == 'coefficients':
            points = self.coefficients.value    # Do I need to reshape this?

            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 2:
                    raise ValueError("The color function must be 2D to plot as a surface.")
                
                color = color.coefficients.value
                if color.size != points.size:
                    # If the number of coefficients are different, just evaluate the color function at the locations of the coefficients of the function.
                    # Generate meshgrid of parametric coordinates
                    mesh_grid_input = []
                    for dimension_index in range(self.space.num_parametric_dimensions):
                        mesh_grid_input.append(np.linspace(0., 1., self.coefficients.shape[dimension_index]))
                    parametric_coordinates_tuple = np.meshgrid(*mesh_grid_input, indexing='ij')
                    for dimensions_index in range(self.space.num_parametric_dimensions):
                        parametric_coordinates_tuple[dimensions_index] = parametric_coordinates_tuple[dimensions_index].reshape((-1,1))
                    parametric_coordinates = np.hstack(parametric_coordinates_tuple)
                    color = color.evaluate(parametric_coordinates).value
        else:
            raise ValueError("Invalid point type. Must be 'evaluated_points' or 'coefficients'.")
        # endregion Generate the points to plot

        # Call general plot surface function to plot the points with the colors
        plotting_elements = pf.plot_surface(points=points, plot_types=plot_types, opacity=opacity, color=color, color_map=color_map, 
                                            surface_texture=surface_texture, line_width=line_width, 
                                            additional_plotting_elements=additional_plotting_elements, show=show)
        return plotting_elements
    

    def plot_volume(self, point_type:str='evaluated_points', plot_types:list=['volume'], opacity:float=1., color:str|Function='#00629B',
                        color_map:str='jet', surface_texture:str="", line_width:float=3., additional_plotting_elements:list=[], show:bool=True):
        '''
        Plots the function as a volume. NOTE: This should only be called if the function is a volume!

        Parameters
        -----------
        points_type : str = 'evaluated_points'
            The type of points to be plotted. {evaluated_points, coefficients}
        plot_types : list = ['volume']
            The type of plot {volume}
        opactity : float = 1.
            The opacity of the plot. 0 is fully transparent and 1 is fully opaque.
        color : str = '#00629B'
            The 6 digit color code to plot the function as. If a function is provided, the function will be used to color the volume.
        color_map : str = 'jet'
            The color map to use if the color is a function.
        surface_texture : str = ""
            The surface texture to determine how light bounces off the surface.
            See https://github.com/marcomusy/vedo/blob/master/examples/basic/lightings.py for options.
        line_width : float = 3.
            The width of the lines if the plot type is wireframe.
        additional_plotting_elemets : list = []
            Vedo plotting elements that may have been returned from previous plotting functions that should be plotted with this plot.
        show : bool = True
            A boolean on whether to show the plot or not. If the plot is not shown, the Vedo plotting elements are still returned.
        
        Returns
        -------
        plotting_elements : list
            The Vedo plotting elements that were plotted.
        '''
        import lsdo_function_spaces.utils.plotting_functions as pf
        if self.space.num_parametric_dimensions != 3:
            raise ValueError("This function is not a volume and cannot be plotted as one.")
        
        # region Generate the points to plot
        if point_type == 'evaluated_points':
            num_points = 50

            # Generate meshgrid of parametric coordinates
            linspace_dimension = np.linspace(0., 1., num_points)
            linspace_meshgrid = np.meshgrid(linspace_dimension, linspace_dimension)
            linspace_dimension1 = linspace_meshgrid[0].reshape((-1,1))
            linspace_dimension2 = linspace_meshgrid[1].reshape((-1,1))
            zeros_dimension = np.zeros((num_points**2,)).reshape((-1,1))
            ones_dimension = np.ones((num_points**2,)).reshape((-1,1))

            parametric_coordinates = []
            parametric_coordinates.append(np.column_stack((linspace_dimension1, linspace_dimension2, zeros_dimension)))
            parametric_coordinates.append(np.column_stack((linspace_dimension1, linspace_dimension2, ones_dimension)))
            parametric_coordinates.append(np.column_stack((linspace_dimension1, zeros_dimension, linspace_dimension2)))
            parametric_coordinates.append(np.column_stack((linspace_dimension1, ones_dimension, linspace_dimension2)))
            parametric_coordinates.append(np.column_stack((zeros_dimension, linspace_dimension1, linspace_dimension2)))
            parametric_coordinates.append(np.column_stack((ones_dimension, linspace_dimension1, linspace_dimension2)))
            
            points = []
            for parametric_coordinate_set in parametric_coordinates:
                points.append(self.evaluate(parametric_coordinate_set).value)

            plotting_colors = []
            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 3:
                    raise ValueError("The color function must be 3D to plot as a volume.")
                
                for parametric_coordinate_set in parametric_coordinates:
                    plotting_colors.append(color.evaluate(parametric_coordinate_set).value)
                color = plotting_colors

        elif point_type == 'coefficients':
            points = []
            points.append(self.coefficients.value[0,:,:])
            points.append(self.coefficients.value[-1,:,:])
            points.append(self.coefficients.value[:,0,:])
            points.append(self.coefficients.value[:,-1,:])
            points.append(self.coefficients.value[:,:,0])
            points.append(self.coefficients.value[:,:,-1])

            if isinstance(color, Function):
                if color.space.num_parametric_dimensions != 3:
                    raise ValueError("The color function must be 3D to plot as a volume.")
                
                color = color.coefficients.value
                if color.size != points.size:
                    raise NotImplementedError("For volumes, please use evaluated points to plot or "
                                              + "use a color function that has the same structure of coefficients.")
        else:
            raise ValueError("Invalid point type. Must be 'evaluated_points' or 'coefficients'.")
        # endregion Generate the points to plot

        # Call general plot volume function to plot the points with the colors
        plotting_elements = additional_plotting_elements.copy()
        for i in range(6):
            if isinstance(color, list):
                plotting_color = color[i]
            else:
                plotting_color = color
            plotting_elements.append(
                pf.plot_surface(points=points[i], plot_types=plot_types, opacity=opacity, color=plotting_color, color_map=color_map,
                                surface_texture=surface_texture, line_width=line_width, show=False)
            )
        if show:
            pf.show_plot(plotting_elements, title="Volume", axes=1, interactive=True)
        return plotting_elements
